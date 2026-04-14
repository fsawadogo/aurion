#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { AurionStack } from "../lib/aurion-stack";

const app = new cdk.App();

new AurionStack(app, "AurionDevStack", {
  environment: "dev",
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: "ca-central-1",
  },
  description: "Aurion Clinical AI - Development Environment",
});

new AurionStack(app, "AurionProdStack", {
  environment: "prod",
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: "ca-central-1",
  },
  description: "Aurion Clinical AI - Production Environment",
});

app.synth();
