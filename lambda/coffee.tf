variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "eu-central-1"
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}


# ECR Repository for Docker image
resource "aws_ecr_repository" "lambda_repository" {
  name = "coffee-lambda"
}

locals {
  file1_md5 = filemd5("Dockerfile")
  file2_md5 = filemd5("lambda_function.py")
  build_hash = md5("${local.file1_md5}-${local.file2_md5}")
}

output "build_hash" {
  value = local.build_hash
}

resource "null_resource" "docker_build_and_push" {
  # Trigger rebuild when changes are detected in the Dockerfile or Python script
  triggers = {
    build_hash = local.build_hash
  }

  provisioner "local-exec" {
    command    = <<-EOT
      docker build -t ${aws_ecr_repository.lambda_repository.repository_url}:${local.build_hash} . &&
      aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${aws_ecr_repository.lambda_repository.repository_url} &&
      docker push ${aws_ecr_repository.lambda_repository.repository_url}:${local.build_hash}
    EOT
    on_failure = fail
  }

  depends_on = [aws_ecr_repository.lambda_repository]
}


# IAM Role for Lambda
resource "aws_iam_role" "lambda_iam_role" {
  name = "lambda_execution_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Effect = "Allow"
        Sid    = ""
      },
    ]
  })

  # IAM Policy to allow Lambda to log to CloudWatch
  inline_policy {
    name = "LambdaCloudWatchLoggingPolicy"
    policy = jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Action = [
            "logs:CreateLogGroup",
            "logs:CreateLogStream",
            "logs:PutLogEvents"
          ],
          Resource = "arn:aws:logs:*:*:*",
          Effect   = "Allow"
        },
        {
          Action = "lambda:InvokeFunction",
          Resource = "arn:aws:lambda:*:*:function:coffee_lambda",
          Effect   = "Allow"
        },
      ]
    })
  }
}

variable "lm-username" {
  description = "La Marzocco cloud username"
  type        = string
  sensitive = true
  
}

variable "lm-password" {
  description = "La Marzocco cloud password"
  type        = string
  sensitive = true
}

variable "lm-name" {
  description = "Target machine name"
  type        = string
  sensitive = true
}

variable "lm-serial" {
  description = "Target machine serial number"
  type        = string
  sensitive = true
}

# Lambda Function 1
resource "aws_lambda_function" "docker_lambda" {
  function_name = "coffee_lambda"
  role          = aws_iam_role.lambda_iam_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.lambda_repository.repository_url}:${local.build_hash}"
  timeout       = 20

  image_config {
    command = ["lambda_function.handler"]
  }

  environment {
    variables = {
      USERNAME = var.lm-username
      PASSWORD = var.lm-password
      NAME = var.lm-name
      SERIAL_NUMBER = var.lm-serial
      docker_build_trigger = "${local.build_hash}"
    }
  }

  depends_on = [null_resource.docker_build_and_push]
}

# API Gateway configuration
resource "aws_api_gateway_rest_api" "lambda_api" {
  name        = "CoffeeAPI"
  description = "API Gateway for La Marzocco cloud"
}

resource "aws_api_gateway_resource" "api_resource" {
  rest_api_id = aws_api_gateway_rest_api.lambda_api.id
  parent_id   = aws_api_gateway_rest_api.lambda_api.root_resource_id
  path_part   = "message"
}

resource "aws_api_gateway_method" "api_method" {
  rest_api_id   = aws_api_gateway_rest_api.lambda_api.id
  resource_id   = aws_api_gateway_resource.api_resource.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "lambda_integration" {
  rest_api_id             = aws_api_gateway_rest_api.lambda_api.id
  resource_id             = aws_api_gateway_resource.api_resource.id
  http_method             = aws_api_gateway_method.api_method.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.docker_lambda.invoke_arn
}

resource "aws_api_gateway_deployment" "api_deployment" {
  depends_on = [
    aws_api_gateway_integration.lambda_integration
  ]

  rest_api_id = aws_api_gateway_rest_api.lambda_api.id
  stage_name  = "prod"

  # Force a new deployment on changes using the correct tolist syntax
  triggers = {
    redeployment = sha1(join(",", tolist([
      jsonencode(aws_api_gateway_method.api_method),
      jsonencode(aws_api_gateway_integration.lambda_integration)
    ])))
  }
}

resource "aws_lambda_permission" "api_gateway_lambda" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.docker_lambda.function_name
  principal     = "apigateway.amazonaws.com"

  # Ensure that the source ARN is specific to the method requesting access
  source_arn = "${aws_api_gateway_rest_api.lambda_api.execution_arn}/*/*"
}

output "lambda_function_name" {
  value = aws_lambda_function.docker_lambda.function_name
}

output "api_gateway_invoke_url" {
  value = "${aws_api_gateway_deployment.api_deployment.invoke_url}/message"
}

# Attach policy to the Lambda role to access SNS
resource "aws_iam_role_policy" "lambda_policy" {
  role   = aws_iam_role.lambda_iam_role.id
  policy = data.aws_iam_policy_document.lambda_policy.json

  depends_on = [
    aws_iam_role.lambda_iam_role
  ]
}

data "aws_iam_policy_document" "lambda_policy" {
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = ["arn:aws:logs:*:*:*"]
  }
}
