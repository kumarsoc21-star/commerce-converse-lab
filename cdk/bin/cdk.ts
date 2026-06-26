#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { CommerceConverseCoreStack } from '../lib/commerce-converse-core-stack';

const app = new cdk.App();

new CommerceConverseCoreStack(app, 'CommerceConverseCoreStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1',
  },
  description:
    'Commerce Converse lab — Bedrock Converse tool loop in Lambda, DynamoDB, and policy KB RAG',
});
