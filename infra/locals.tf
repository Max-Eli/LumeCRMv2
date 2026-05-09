# Shared local values — naming, AZ list, common tags.
#
# `name_prefix` is the foundation for every resource name. Sticking to
# `<project>-<env>-<role>` makes resources sortable in the console and
# scriptable to filter via the AWS CLI.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name_prefix = "lume-${var.environment}"

  # The first N AZs in the region. Production uses 2; pin to 3 if
  # operational complexity is ever worth the extra cross-AZ cost.
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  # Public subnets host the ALB + NAT; private subnets host
  # everything else (Fargate tasks, RDS). /24 each = 256 IPs which
  # is plenty for our scale.
  public_subnet_cidrs = [
    for i in range(var.az_count) :
    cidrsubnet(var.vpc_cidr, 8, i)
  ]
  private_subnet_cidrs = [
    for i in range(var.az_count) :
    cidrsubnet(var.vpc_cidr, 8, i + 10)
  ]
}
