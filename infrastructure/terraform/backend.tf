terraform {
  backend "gcs" {
    bucket = "retikon-terraform-state-simitor"
    prefix = "retikon/terraform"
  }
}
