# `s3-glacier-restore`

Experimental Python 3 script to perform full restoring / transition for Glacier
objects in S3.

## How to Use

You will need `boto3` to be installed in your Python environment.

Also, this set-up assumes at least Python 3.6 because of the type annotations
and `f-string` syntax used.

If you cannot upgrade your Python to at least 3.6, consider using building the
Dockerfile and use that instead. See [here](#Dockerfile-Usage) for more details.

### Example commands for Running Script on Host

```bash
# All the commands obey `boto3`'s way of getting the AWS credentials
# i.e. common way includes setting up `~/.aws/credentials`

# List all Glacier objects in bucket for certain prefix (prefix is optional)
./s3-glacier-restore.py list -b my-bucket -p my-prefix/

# Perform Restore request on all listed Glacier objects shown in `list`
# See: https://docs.aws.amazon.com/AmazonS3/latest/dev/restoring-objects.html
./s3-glacier-restore.py restore -b my-bucket -p my-prefix/ \
    --days 7 --tier Bulk 2>&1 | \
    tee restore.log

# Perform Restore request + sleep loop to transit all listed Glacier objects
# shown in `list`, default to poll at every 1 hour
# See: https://aws.amazon.com/premiumsupport/knowledge-center/restore-s3-object-glacier-storage-class/
./s3-glacier-restore.py transit -b my-bucket -p my-prefix/ \
    --days 7 --tier Bulk --storage-class INTELLIGENT_TIERING 2>&1 | \
    tee transit.log

# Check Restore status of all objects in bucket for a certain prefix (prefix is optional)
./s3-glacier-restore.py check_restore -b my-bucket -p my-prefix/
```

For more command argument details, type `./s3-glacier-restore.py --help`.

### Dockerfile Usage

You will need `docker` command to run the commands below.

Building the `Dockerfile`:

```bash
docker build . -t s3-glacier-restore
```

Running the commands (similar to running on host):

```bash
export AWS_ACCESS_KEY_ID=...  # Fill in the actual value
export AWS_SECRET_ACCESS_KEY=...  # Fill in the actual value
DOCKER_CMD="docker run -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY s3-glacier-restore"

# List all Glacier objects in bucket for certain prefix (prefix is optional)
${DOCKER_CMD} list -b my-bucket -p my-prefix/

# Perform Restore request on all listed Glacier objects shown in `list`
# See: https://docs.aws.amazon.com/AmazonS3/latest/dev/restoring-objects.html
${DOCKER_CMD} restore -b my-bucket -p my-prefix/ \
    --days 7 --tier Bulk 2>&1 | \
    tee restore.log

# Perform Restore request + sleep loop to transit all listed Glacier objects
# shown in `list`, default to poll at every 1 hour
# See: https://aws.amazon.com/premiumsupport/knowledge-center/restore-s3-object-glacier-storage-class/
${DOCKER_CMD} transit -b my-bucket -p my-prefix/ \
    --days 7 --tier Bulk --storage-class INTELLIGENT_TIERING 2>&1 | \
    tee transit.log

# Check Restore status of all objects in bucket for a certain prefix (prefix is optional)
${DOCKER_CMD} check_restore -b my-bucket -p my-prefix/
```

## Limitations

Only works for `GLACIAL` for now, and can only perform Glacial restore given the
number of days to restore for and the retrieval tier.

Also the `transit` operation just a dumb loop to keep trying the transiting all
the listed objects to a particular Storage Class. It will however, check not
attempt to transit objects that are not of `GLACIAL` Storage Class, if it
happens that some of the restored objects have already been transited in a
previous loop.
