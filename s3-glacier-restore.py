#!/usr/bin/env python3
import argparse
import boto3
from enum import Enum
import logging
import time
from typing import List, Optional

logging.basicConfig(format="[%(levelname)s] %(message)s")
logger = logging.getLogger("root")


class Operation(Enum):
    """
    List-only operation. No other actions will take place.
    """
    List = "list"

    """
    List and Restore operation. The operation is immediate, but S3 Glacier would require a good
    couple of hours (depending on Tier) before the S3 object is restored.
    """
    Restore = "restore"

    """
    List, Restore and Transit operation. This is a polling action and will only complete after all
    the listed Glacier files have been successfully transitted from Glacier
    """
    Transit = "transit"

    """
    Check Restore status of a single object.
    """
    CheckRestore = "check_restore"

    def __str__(self):
        return self.value


class LogLevel(Enum):
    Debug = "DEBUG"
    Info = "INFO"
    Warning = "WARNING"
    Error = "ERROR"
    Critical = "CRITICAL"

    def __str__(self):
        return self.value

    def to_val(self):
        LOG_LEVEL = {
            self.Debug: logging.DEBUG,
            self.Info: logging.INFO,
            self.Warning: logging.WARNING,
            self.Error: logging.ERROR,
            self.Critical: logging.CRITICAL,
        }
        return LOG_LEVEL[self]


class Tier(Enum):
    Expedited = "Expedited"
    Standard = "Standard"
    Bulk = "Bulk"

    def __str__(self):
        return self.value


class StorageClass(Enum):
    Standard = "STANDARD"
    StandardInfrequentAccess = "STANDARD_IA"
    OneZoneInfrequentAccess = "ONEZONE_IA"
    IntelligentTiering = "INTELLIGENT_TIERING"

    def __str__(self):
        return self.value

def list_objects(
        s3: boto3.Session,
        bucket: str,
        prefix: str,
        glacier: bool,
        print: bool) -> List[str]:
    s3 = boto3.client("s3")
    keys = []

    is_continuing = True
    kwargs = {}
    
    while is_continuing:
        rsp = s3.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix,
            **kwargs,
        )
        if "Contents" in rsp:
            for obj in rsp["Contents"]:
                key = obj["Key"]
                if glacier:
                    if obj["StorageClass"] == "GLACIER":
                        keys.append(key)
                        if print: logger.debug(key)
                else:
                    keys.append(key)
                    if print: logger.debug(key)

        if "NextContinuationToken" in rsp:
            continuation_token = rsp["NextContinuationToken"]
            kwargs["ContinuationToken"] = continuation_token
        else:
            is_continuing = False

    return keys


def restore_glacier_objects(
        s3: boto3.Session,
        bucket: str,
        keys: List[str],
        days: int,
        tier: Tier,
        continue_on_restore_already_in_progress: bool = True,
        continue_on_other_errors: bool = True) -> None:

    def impl(s3, bucket, key, days, tier):
        logger.debug(f"Restoring \"{key}\"")
        s3.restore_object(
            Bucket=bucket,
            Key=key,
            RestoreRequest={
                "Days": days,
                "GlacierJobParameters": {
                    "Tier": str(tier),
                },
            },
        )
        logger.debug(f"Successfully sent Restore request for \"{key}\"")

    if continue_on_restore_already_in_progress:
        for key in keys:
            try:
                impl(s3, bucket, key, days, tier)
            except s3.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "RestoreAlreadyInProgress":
                    logger.warning(e)
                elif continue_on_other_errors:
                    logger.error(e)
                    logger.warning("Continuing because `continue_on_other_errors` is set to `True`")
                else:
                    raise e
    else:
        for key in keys:
            impl(s3, bucket, key, days, tier)


def transit_glacier_objects(
        s3: boto3.Session,
        bucket: str,
        keys: List[str],
        storage_class: StorageClass,
        poll_seconds: int) -> None:

    def transit_once(s3, bucket, keys):
        has_at_least_one_untransited = False

        for key in keys:
            try:
                # Ignore files that are no longer GLACIER to save costs
                rsp = s3.list_objects_v2(
                    Bucket=bucket,
                    Prefix=key,
                )
                assert len(rsp["Contents"]) == 1
                obj = rsp["Contents"][0]
                if obj["StorageClass"] != "GLACIER":
                    logger.debug(f"Skipping \"{key}\" because it it no longer a GLACIER object")
                    continue

                # Actual transiting
                logger.debug(f"Transiting \"{key}\" back to storage class [{str(storage_class)}]")
                s3.copy_object(
                    Bucket=bucket,
                    CopySource={
                        "Bucket": bucket,
                        "Key": key,
                    },
                    Key=key,
                    StorageClass=str(storage_class),
                )
                logger.debug(f"Transiting \"{key}\" successful!")
            except s3.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "InvalidObjectState":
                    has_at_least_one_untransited = True
                    logger.warning(e)
                else:
                    raise e

        return has_at_least_one_untransited

    while True:
        has_at_least_one_untransited = transit_once(s3, bucket, keys)
        if not has_at_least_one_untransited:
            break

        time.sleep(poll_seconds)

def check_restore_status(
        s3: boto3.Session,
        bucket: str,
        key: str) -> None:

    s3 = boto3.client("s3")
    rsp = s3.head_object(
        Bucket=bucket,
        Key=key,
    )
    if "Restore" in rsp:
        status = rsp["Restore"]
        logger.debug(f"Restore status for {key}: {status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore glacier objects helper")
    parser.add_argument("op", type=Operation, choices=list(Operation),
                        help="operation to perform")
    parser.add_argument("-b", "--bucket", dest="bucket", required=True,
                        help="bucket to perform operations")
    parser.add_argument("-p", "--prefix", dest="prefix",
                        help="prefix to perform operations recursive on")
    parser.add_argument("-l", "--log_level", dest="log_level",
                        type=LogLevel, choices=list(LogLevel),
                        default=LogLevel.Debug,
                        help="logging level to set")

    # Cannot use argument group because of overlaps
    # Restore grouping
    parser.add_argument("--days", dest="days",
                        help="(restore | transit) Number of days to restore the Glacier object for")
    parser.add_argument("--tier", dest="tier", type=Tier, choices=list(Tier),
                        help="(restore | transit) Glacier restore tier")

    # Transit grouping (includes Restore)
    parser.add_argument("--storage-class", dest="storage_class",
                        type=StorageClass, choices=list(StorageClass),
                        help="(transit) Storage class to transit back to")
    parser.add_argument("--poll", dest="poll_seconds", type=int, default=3600,  # Every hour
                        help="(transit) Polling interval in seconds to retry transition")

    args = parser.parse_args()

    # Set logging level first
    logger.setLevel(args.log_level.to_val())

    bucket = args.bucket
    logger.debug(f"Bucket: {bucket}")
    prefix = args.prefix if args.prefix else ""
    logger.debug(f"Prefix: {prefix}")

    s3 = boto3.client("s3")

    if args.op == Operation.List:
        list_objects(s3, bucket, prefix, glacier=True, print=True)
        logger.info("Done listing Glacier objects!")
    elif args.op == Operation.Restore:
        assert args.days and str.isdigit(args.days), "--days must be set to an integer"
        days = int(args.days)
        logger.debug(f"Restore retrieval days: {days}")
        
        assert args.tier, "--tier must be set"
        tier = args.tier
        logger.debug(f"Restore retrieval tier: {str(tier)}")

        keys = list_objects(s3, bucket, prefix, glacier=True, print=False)
        restore_glacier_objects(s3, bucket, keys, days, tier)
        logger.info("Done listing and restoring Glacier objects!")
    elif args.op == Operation.Transit:
        assert args.days and str.isdigit(args.days), "--days must be set to an integer"
        days = int(args.days)
        logger.debug(f"Restore retrieval days: {days}")
        
        assert args.tier, "--tier must be set"
        tier = args.tier
        logger.debug(f"Restore retrieval tier: {str(tier)}")

        assert args.storage_class, "--storage-class must be set"
        storage_class = args.storage_class
        logger.debug(f"Transit storage class: {str(storage_class)}")

        poll_seconds = args.poll_seconds

        keys = list_objects(s3, bucket, prefix, glacier=True, print=False)
        restore_glacier_objects(s3, bucket, keys, days, tier)
        transit_glacier_objects(s3, bucket, keys, storage_class, poll_seconds)
        logger.info("Done listing, restoring and transiting Glacier objects!")
    elif args.op == Operation.CheckRestore:
        keys = list_objects(s3, bucket, prefix, glacier=False, print=False)
        for key in keys:
            check_restore_status(s3, bucket, key)
