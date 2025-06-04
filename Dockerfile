FROM public.ecr.aws/lambda/python:3.12
ENV UV_SYSTEM_PYTHON=1
# Install uv
RUN pip install uv

# Copy uv.lock and pyproject.toml
COPY uv.lock pyproject.toml ${LAMBDA_TASK_ROOT}/

WORKDIR ${LAMBDA_TASK_ROOT}

RUN uv pip install . --system
# Install dependencies from uv.lock

# Copy function code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler (could also be done as a parameter override outside of the Dockerfile)
CMD [ "lambda_function.handler" ]
