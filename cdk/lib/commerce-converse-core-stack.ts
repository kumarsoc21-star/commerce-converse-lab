import * as cdk from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as triggers from 'aws-cdk-lib/triggers';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
import { Construct } from 'constructs';
import * as path from 'path';

export class CommerceConverseCoreStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const prefix = 'commerce-converse';
    const region = cdk.Stack.of(this).region;
    const account = cdk.Stack.of(this).account;
    const embedModelArn = `arn:aws:bedrock:${region}::foundation-model/amazon.titan-embed-text-v2:0`;

    const ragPrefix = `${prefix}-core`;
    const guidesAssetPath = path.join(__dirname, '../../converse-content/store-guides');

    const policyDocsBucket = new s3.Bucket(this, 'ConversePolicyDocsBucket', {
      bucketName: `${ragPrefix}-policy-docs-${account}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
    });

    const vectorBucketName = `${ragPrefix}-vector-store-${account}`;
    const vectorIndexName = `${ragPrefix}-policy-index`;

    const vectorBucket = new s3vectors.CfnVectorBucket(this, 'ConverseVectorBucket', {
      vectorBucketName,
    });
    vectorBucket.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);

    const vectorIndex = new s3vectors.CfnIndex(this, 'ConverseVectorIndex', {
      vectorBucketName,
      indexName: vectorIndexName,
      dimension: 1024,
      distanceMetric: 'cosine',
      dataType: 'float32',
      metadataConfiguration: {
        nonFilterableMetadataKeys: ['AMAZON_BEDROCK_TEXT_CHUNK', 'AMAZON_BEDROCK_METADATA'],
      },
    });
    vectorIndex.addDependency(vectorBucket);
    vectorIndex.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);

    const kbRole = new iam.Role(this, 'ConverseKnowledgeBaseRole', {
      roleName: `${ragPrefix}-kb-role`,
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
      description: 'Bedrock Knowledge Base role for commerce-converse-lab',
    });

    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['s3:GetObject', 's3:ListBucket'],
        resources: [policyDocsBucket.bucketArn, `${policyDocsBucket.bucketArn}/*`],
      }),
    );

    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['s3vectors:*'],
        resources: [`arn:aws:s3vectors:${region}:${account}:bucket/*`],
      }),
    );

    kbRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel'],
        resources: [embedModelArn],
      }),
    );

    const knowledgeBase = new bedrock.CfnKnowledgeBase(this, 'ConverseKnowledgeBase', {
      name: `${ragPrefix}-kb`,
      description: 'Policy and FAQ knowledge base for commerce-converse-lab (S3 Vectors)',
      roleArn: kbRole.roleArn,
      knowledgeBaseConfiguration: {
        type: 'VECTOR',
        vectorKnowledgeBaseConfiguration: {
          embeddingModelArn: embedModelArn,
          embeddingModelConfiguration: {
            bedrockEmbeddingModelConfiguration: {
              dimensions: 1024,
            },
          },
        },
      },
      storageConfiguration: {
        type: 'S3_VECTORS',
        s3VectorsConfiguration: {
          indexArn: vectorIndex.attrIndexArn,
        },
      },
    });
    knowledgeBase.node.addDependency(kbRole);
    knowledgeBase.addDependency(vectorIndex);

    const dataSource = new bedrock.CfnDataSource(this, 'ConversePolicyDataSource', {
      name: `${ragPrefix}-policy-source`,
      knowledgeBaseId: knowledgeBase.attrKnowledgeBaseId,
      dataSourceConfiguration: {
        type: 'S3',
        s3Configuration: {
          bucketArn: policyDocsBucket.bucketArn,
          inclusionPrefixes: ['store-guides/'],
        },
      },
      vectorIngestionConfiguration: {
        chunkingConfiguration: {
          chunkingStrategy: 'FIXED_SIZE',
          fixedSizeChunkingConfiguration: {
            maxTokens: 512,
            overlapPercentage: 20,
          },
        },
      },
    });

    const lambdaAsset = path.join(__dirname, '../lambda');

    const ingestionFn = new lambda.Function(this, 'ConverseIngestionFn', {
      functionName: `${ragPrefix}-start-ingestion`,
      description: 'Starts Bedrock KB ingestion after policy docs upload',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'start_ingestion.lambda_handler',
      code: lambda.Code.fromAsset(lambdaAsset),
      memorySize: 128,
      timeout: cdk.Duration.seconds(30),
      environment: {
        KNOWLEDGE_BASE_ID: knowledgeBase.attrKnowledgeBaseId,
        DATA_SOURCE_ID: dataSource.attrDataSourceId,
      },
    });

    ingestionFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:StartIngestionJob', 'bedrock:GetIngestionJob', 'bedrock:ListIngestionJobs'],
        resources: [knowledgeBase.attrKnowledgeBaseArn],
      }),
    );

    const guidesUpload = new s3deploy.BucketDeployment(this, 'ConverseGuidesUpload', {
      sources: [s3deploy.Source.asset(guidesAssetPath)],
      destinationBucket: policyDocsBucket,
      destinationKeyPrefix: 'store-guides/',
      prune: true,
    });

    ingestionFn.addEnvironment('GUIDES_FINGERPRINT', cdk.FileSystem.fingerprint(guidesAssetPath));

    const ingestionTrigger = new triggers.Trigger(this, 'ConverseIngestionTrigger', {
      handler: ingestionFn,
      executeOnHandlerChange: true,
      executeAfter: [guidesUpload],
    });

    const catalogTable = new dynamodb.Table(this, 'ConverseCatalogTable', {
      tableName: 'converse-trail-catalog',
      partitionKey: { name: 'trailSku', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    catalogTable.addGlobalSecondaryIndex({
      indexName: 'trail-dept-price-index',
      partitionKey: { name: 'trailDeptKey', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'emberPrice', type: dynamodb.AttributeType.NUMBER },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    const cartTable = new dynamodb.Table(this, 'ConverseCartTable', {
      tableName: 'converse-ember-cart',
      partitionKey: { name: 'emberShopperId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'trailSku', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const casesTable = new dynamodb.Table(this, 'ConverseCasesTable', {
      tableName: 'converse-ember-tickets',
      partitionKey: { name: 'emberShopperId', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'supportTicketRef', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const lambdaEnv: Record<string, string> = {
      CATALOG_TABLE: catalogTable.tableName,
      CART_TABLE: cartTable.tableName,
      CASES_TABLE: casesTable.tableName,
      GEN_MODEL_ID: 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
      KNOWLEDGE_BASE_ID: knowledgeBase.attrKnowledgeBaseId,
    };

    const chatFn = new lambda.Function(this, 'ConverseChatFn', {
      functionName: 'commerce-converse-chat',
      description: 'Bedrock Converse tool loop for commerce assistant',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'chat_handler.lambda_handler',
      code: lambda.Code.fromAsset(lambdaAsset),
      memorySize: 512,
      timeout: cdk.Duration.seconds(30),
      environment: lambdaEnv,
    });

    const bootstrapFn = new lambda.Function(this, 'ConverseBootstrapFn', {
      functionName: 'commerce-converse-bootstrap',
      description: 'Seeds converse-catalog table on stack deploy',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'bootstrap_catalog.lambda_handler',
      code: lambda.Code.fromAsset(lambdaAsset),
      memorySize: 256,
      timeout: cdk.Duration.minutes(2),
      environment: { CATALOG_TABLE: catalogTable.tableName },
    });

    catalogTable.grantReadData(chatFn);
    catalogTable.grantReadWriteData(bootstrapFn);
    cartTable.grantReadWriteData(chatFn);
    casesTable.grantReadWriteData(chatFn);

    chatFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel', 'bedrock:Converse'],
        resources: ['*'],
      }),
    );

    chatFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:Retrieve'],
        resources: [knowledgeBase.attrKnowledgeBaseArn],
      }),
    );

    new triggers.Trigger(this, 'ConverseCatalogSeedTrigger', {
      handler: bootstrapFn,
      executeOnHandlerChange: true,
    });

    const corsPreflight: apigwv2.CorsPreflightOptions = {
      allowHeaders: ['Content-Type'],
      allowMethods: [
        apigwv2.CorsHttpMethod.GET,
        apigwv2.CorsHttpMethod.POST,
        apigwv2.CorsHttpMethod.OPTIONS,
      ],
      allowOrigins: ['*'],
    };

    const httpApi = new apigwv2.HttpApi(this, 'ConverseHttpApi', {
      apiName: 'CommerceConverseApi',
      description: 'HTTP API for commerce-converse-lab (Bedrock Converse + Lambda)',
      corsPreflight,
    });

    const chatIntegration = new integrations.HttpLambdaIntegration('ConverseChatIntegration', chatFn);

    httpApi.addRoutes({ path: '/health', methods: [apigwv2.HttpMethod.GET], integration: chatIntegration });
    httpApi.addRoutes({ path: '/chat', methods: [apigwv2.HttpMethod.POST], integration: chatIntegration });
    httpApi.addRoutes({ path: '/cart', methods: [apigwv2.HttpMethod.GET], integration: chatIntegration });
    httpApi.addRoutes({
      path: '/cart/place',
      methods: [apigwv2.HttpMethod.POST],
      integration: chatIntegration,
    });
    httpApi.addRoutes({
      path: '/cart/remove',
      methods: [apigwv2.HttpMethod.POST],
      integration: chatIntegration,
    });
    httpApi.addRoutes({
      path: '/cart/clear',
      methods: [apigwv2.HttpMethod.POST],
      integration: chatIntegration,
    });

    new cdk.CfnOutput(this, 'HttpApiId', {
      value: httpApi.httpApiId,
      description: 'Set as commerceConverseApiId context in my-portfolio-lab CDK for /converse-lab proxy',
    });

    new cdk.CfnOutput(this, 'ApiUrl', {
      description: 'HTTP API base URL — set NEXT_PUBLIC_API_URL in web/.env.local',
      value: httpApi.apiEndpoint,
    });

    new cdk.CfnOutput(this, 'KnowledgeBaseId', {
      value: knowledgeBase.attrKnowledgeBaseId,
      description: 'Bedrock Knowledge Base for lookup_policies',
    });

    new cdk.CfnOutput(this, 'PolicyDocsBucketName', {
      value: policyDocsBucket.bucketName,
    });

    new cdk.CfnOutput(this, 'CatalogTableName', { value: catalogTable.tableName });
    new cdk.CfnOutput(this, 'CartTableName', { value: cartTable.tableName });
    new cdk.CfnOutput(this, 'ChatFunctionName', { value: chatFn.functionName });
  }
}
