# Local testing
Supported actions: `get_status`, `turn_on`, `turn_off`, `list_machines` (will probably be removed or refactored)

```bash
docker build -t coffee-lambda .
docker run -it \
    -p 8080:8080 \
    -e USERNAME="*****" \
    -e PASSWORD="*****" \
    -e SERIAL_NUMBER="*****" \
    -e NAME="*****" coffee-lambda 

curl "http://localhost:8080/2015-03-31/functions/function/invocations" -d '{"action":"get_status"}' | jq
```

# Deploying to AWS
Could not get SSO to work, TBD tomorrow
