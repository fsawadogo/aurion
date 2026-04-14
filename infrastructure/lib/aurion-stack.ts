import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as ecs_patterns from "aws-cdk-lib/aws-ecs-patterns";
import * as rds from "aws-cdk-lib/aws-rds";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as kms from "aws-cdk-lib/aws-kms";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as appconfig from "aws-cdk-lib/aws-appconfig";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as logs from "aws-cdk-lib/aws-logs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as autoscaling from "aws-cdk-lib/aws-autoscaling";

// ---------------------------------------------------------------------------
// Stack Props
// ---------------------------------------------------------------------------

export interface AurionStackProps extends cdk.StackProps {
  environment: "dev" | "prod";
}

// ---------------------------------------------------------------------------
// Main Stack
// ---------------------------------------------------------------------------

export class AurionStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: AurionStackProps) {
    super(scope, id, props);

    const env = props.environment;
    const isProd = env === "prod";

    // Apply mandatory tags to every resource in this stack
    cdk.Tags.of(this).add("Project", "aurion");
    cdk.Tags.of(this).add("Environment", env);
    cdk.Tags.of(this).add("DataClassification", "phi-adjacent");

    // -----------------------------------------------------------------------
    // KMS — Customer-managed encryption key
    // -----------------------------------------------------------------------

    const encryptionKey = new kms.Key(this, "EncryptionKey", {
      alias: `aurion-key-${env}`,
      description: `Aurion ${env} encryption key for S3 and RDS`,
      enableKeyRotation: true,
      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
    });

    // -----------------------------------------------------------------------
    // VPC
    // -----------------------------------------------------------------------

    const vpc = new ec2.Vpc(this, "Vpc", {
      vpcName: `aurion-vpc-${env}`,
      maxAzs: 2,
      natGateways: isProd ? 2 : 1,
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: "Public",
          subnetType: ec2.SubnetType.PUBLIC,
        },
        {
          cidrMask: 24,
          name: "Private",
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
        },
        {
          cidrMask: 24,
          name: "Isolated",
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
        },
      ],
    });

    // -----------------------------------------------------------------------
    // RDS PostgreSQL
    // -----------------------------------------------------------------------

    const dbSecurityGroup = new ec2.SecurityGroup(this, "DbSecurityGroup", {
      vpc,
      description: "Security group for Aurion RDS instance",
      allowAllOutbound: false,
    });

    const dbInstance = new rds.DatabaseInstance(this, "Database", {
      instanceIdentifier: `aurion-db-${env}`,
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_15,
      }),
      instanceType: ec2.InstanceType.of(
        ec2.InstanceClass.T3,
        ec2.InstanceSize.MEDIUM
      ),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [dbSecurityGroup],
      databaseName: "aurion",
      credentials: rds.Credentials.fromGeneratedSecret("aurion", {
        secretName: `aurion/db-credentials-${env}`,
      }),
      storageEncrypted: true,
      storageEncryptionKey: encryptionKey,
      multiAz: isProd,
      deletionProtection: isProd,
      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
      backupRetention: isProd ? cdk.Duration.days(30) : cdk.Duration.days(7),
      allocatedStorage: 20,
      maxAllocatedStorage: isProd ? 100 : 50,
    });

    // -----------------------------------------------------------------------
    // DynamoDB — Audit Log
    // -----------------------------------------------------------------------

    const auditLogTable = new dynamodb.Table(this, "AuditLogTable", {
      tableName: `aurion-audit-log-${env}`,
      partitionKey: { name: "session_id", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "event_timestamp", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: encryptionKey,
    });

    // -----------------------------------------------------------------------
    // S3 Buckets
    // -----------------------------------------------------------------------

    const audioBucket = new s3.Bucket(this, "AudioBucket", {
      bucketName: `aurion-audio-${env}-${this.account}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: encryptionKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: !isProd,
      lifecycleRules: [
        {
          id: "expire-audio",
          expiration: cdk.Duration.days(1),
          enabled: true,
        },
      ],
      versioned: false,
      enforceSSL: true,
    });

    const framesBucket = new s3.Bucket(this, "FramesBucket", {
      bucketName: `aurion-frames-${env}-${this.account}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: encryptionKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: !isProd,
      lifecycleRules: [
        {
          id: "expire-frames",
          expiration: cdk.Duration.days(1),
          enabled: true,
        },
      ],
      versioned: false,
      enforceSSL: true,
    });

    const evalBucket = new s3.Bucket(this, "EvalBucket", {
      bucketName: `aurion-eval-${env}-${this.account}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: encryptionKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: !isProd,
      versioned: false,
      enforceSSL: true,
      // No lifecycle rule — eval data is retained
    });

    // -----------------------------------------------------------------------
    // Cognito User Pool
    // -----------------------------------------------------------------------

    const userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: `aurion-${env}`,
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      passwordPolicy: {
        minLength: 12,
        requireUppercase: true,
        requireLowercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
    });

    const userPoolClient = new cognito.UserPoolClient(this, "UserPoolClient", {
      userPool,
      userPoolClientName: `aurion-client-${env}`,
      generateSecret: false,
      authFlows: {
        userPassword: true,
        userSrp: true,
      },
      preventUserExistenceErrors: true,
    });

    // Cognito groups matching application roles
    const groups = [
      "CLINICIAN",
      "EVAL_TEAM",
      "COMPLIANCE_OFFICER",
      "ADMIN",
    ];
    for (const groupName of groups) {
      new cognito.CfnUserPoolGroup(this, `Group${groupName}`, {
        userPoolId: userPool.userPoolId,
        groupName,
        description: `Aurion ${groupName} role`,
      });
    }

    // -----------------------------------------------------------------------
    // ECS Cluster
    // -----------------------------------------------------------------------

    const cluster = new ecs.Cluster(this, "Cluster", {
      clusterName: `aurion-${env}`,
      vpc,
      containerInsights: true,
    });

    // -- FastAPI Fargate Service --------------------------------------------

    const apiLogGroup = new logs.LogGroup(this, "ApiLogGroup", {
      logGroupName: `/aurion/${env}/api`,
      retention: isProd
        ? logs.RetentionDays.ONE_YEAR
        : logs.RetentionDays.ONE_WEEK,
      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
    });

    const apiTaskDef = new ecs.FargateTaskDefinition(this, "ApiTaskDef", {
      memoryLimitMiB: isProd ? 2048 : 1024,
      cpu: isProd ? 1024 : 512,
    });

    apiTaskDef.addContainer("api", {
      containerName: "aurion-api",
      image: ecs.ContainerImage.fromAsset("../backend"),
      portMappings: [{ containerPort: 8000 }],
      environment: {
        APP_ENV: env,
        LOG_LEVEL: isProd ? "INFO" : "DEBUG",
        AWS_DEFAULT_REGION: "ca-central-1",
      },
      secrets: {
        DATABASE_URL: ecs.Secret.fromSecretsManager(
          dbInstance.secret!,
          "host"
        ),
      },
      logging: ecs.LogDrivers.awsLogs({
        logGroup: apiLogGroup,
        streamPrefix: "api",
      }),
      healthCheck: {
        command: [
          "CMD-SHELL",
          "curl -f http://localhost:8000/health || exit 1",
        ],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60),
      },
    });

    const apiService =
      new ecs_patterns.ApplicationLoadBalancedFargateService(
        this,
        "ApiService",
        {
          cluster,
          serviceName: `aurion-api-${env}`,
          taskDefinition: apiTaskDef,
          desiredCount: isProd ? 2 : 1,
          publicLoadBalancer: true,
          listenerPort: 80,
          assignPublicIp: false,
          taskSubnets: {
            subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          },
        }
      );

    // Auto-scaling: 1-4 tasks
    const scaling = apiService.service.autoScaleTaskCount({
      minCapacity: 1,
      maxCapacity: 4,
    });

    scaling.scaleOnCpuUtilization("CpuScaling", {
      targetUtilizationPercent: 70,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(60),
    });

    scaling.scaleOnMemoryUtilization("MemoryScaling", {
      targetUtilizationPercent: 80,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(60),
    });

    // Allow API to connect to RDS
    dbSecurityGroup.addIngressRule(
      apiService.service.connections.securityGroups[0],
      ec2.Port.tcp(5432),
      "Allow FastAPI to connect to PostgreSQL"
    );

    // Grant API access to AWS resources
    audioBucket.grantReadWrite(apiTaskDef.taskRole);
    framesBucket.grantReadWrite(apiTaskDef.taskRole);
    evalBucket.grantReadWrite(apiTaskDef.taskRole);
    auditLogTable.grantReadWriteData(apiTaskDef.taskRole);
    encryptionKey.grantEncryptDecrypt(apiTaskDef.taskRole);

    // AppConfig read permission for API
    apiTaskDef.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: [
          "appconfig:GetLatestConfiguration",
          "appconfig:StartConfigurationSession",
        ],
        resources: ["*"],
      })
    );

    // Secrets Manager read for AI provider keys
    apiTaskDef.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ["secretsmanager:GetSecretValue"],
        resources: [
          `arn:aws:secretsmanager:ca-central-1:${this.account}:secret:aurion/*`,
        ],
      })
    );

    // Comprehend Medical for PHI audit
    apiTaskDef.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: [
          "comprehendmedical:DetectEntitiesV2",
          "comprehendmedical:DetectPHI",
        ],
        resources: ["*"],
      })
    );

    // Textract for screen capture OCR
    apiTaskDef.taskRole.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ["textract:AnalyzeDocument", "textract:DetectDocumentText"],
        resources: ["*"],
      })
    );

    // -- Whisper GPU Service (EC2 capacity provider) --------------------------

    const whisperLogGroup = new logs.LogGroup(this, "WhisperLogGroup", {
      logGroupName: `/aurion/${env}/whisper`,
      retention: isProd
        ? logs.RetentionDays.ONE_YEAR
        : logs.RetentionDays.ONE_WEEK,
      removalPolicy: isProd
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
    });

    const whisperAsg = new autoscaling.AutoScalingGroup(this, "WhisperAsg", {
      autoScalingGroupName: `aurion-whisper-asg-${env}`,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      instanceType: new ec2.InstanceType("g4dn.xlarge"),
      machineImage: ecs.EcsOptimizedImage.amazonLinux2(
        ecs.AmiHardwareType.GPU
      ),
      minCapacity: isProd ? 1 : 0,
      maxCapacity: isProd ? 2 : 1,
      cooldown: cdk.Duration.seconds(300),
    });

    const whisperCapacityProvider = new ecs.AsgCapacityProvider(
      this,
      "WhisperCapacityProvider",
      {
        autoScalingGroup: whisperAsg,
        capacityProviderName: `aurion-whisper-cp-${env}`,
        enableManagedScaling: true,
        enableManagedTerminationProtection: isProd,
      }
    );

    cluster.addAsgCapacityProvider(whisperCapacityProvider);

    const whisperTaskDef = new ecs.Ec2TaskDefinition(this, "WhisperTaskDef", {
      networkMode: ecs.NetworkMode.AWS_VPC,
    });

    whisperTaskDef.addContainer("whisper", {
      containerName: "aurion-whisper",
      image: ecs.ContainerImage.fromRegistry(
        "onerahmet/openai-whisper-asr-webservice:latest"
      ),
      memoryLimitMiB: 14336, // ~14GB — leave headroom on g4dn.xlarge (16GB)
      gpuCount: 1,
      portMappings: [{ containerPort: 9000 }],
      environment: {
        ASR_MODEL: "large-v3",
        ASR_ENGINE: "openai_whisper",
      },
      logging: ecs.LogDrivers.awsLogs({
        logGroup: whisperLogGroup,
        streamPrefix: "whisper",
      }),
      healthCheck: {
        command: [
          "CMD-SHELL",
          "curl -f http://localhost:9000/health || exit 1",
        ],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        retries: 3,
        startPeriod: cdk.Duration.seconds(120),
      },
    });

    const whisperService = new ecs.Ec2Service(this, "WhisperService", {
      cluster,
      serviceName: `aurion-whisper-${env}`,
      taskDefinition: whisperTaskDef,
      desiredCount: isProd ? 1 : 0,
      capacityProviderStrategies: [
        {
          capacityProvider: whisperCapacityProvider.capacityProviderName,
          weight: 1,
        },
      ],
    });

    // Grant Whisper access to audio bucket for direct reads
    audioBucket.grantRead(whisperTaskDef.taskRole);
    encryptionKey.grantDecrypt(whisperTaskDef.taskRole);

    // -----------------------------------------------------------------------
    // AppConfig
    // -----------------------------------------------------------------------

    const appConfigApp = new appconfig.CfnApplication(this, "AppConfigApp", {
      name: "aurion",
      description: `Aurion Clinical AI configuration — ${env}`,
    });

    const appConfigEnv = new appconfig.CfnEnvironment(
      this,
      "AppConfigEnv",
      {
        applicationId: appConfigApp.ref,
        name: env,
        description: `Aurion ${env} environment`,
      }
    );

    const appConfigProfile = new appconfig.CfnConfigurationProfile(
      this,
      "AppConfigProfile",
      {
        applicationId: appConfigApp.ref,
        name: "aurion-config",
        locationUri: "hosted",
        description: "Aurion runtime configuration — providers, model params, feature flags",
        type: "AWS.Freeform",
      }
    );

    // Default configuration document
    const defaultConfig = JSON.stringify(
      {
        providers: {
          transcription: "whisper",
          note_generation: "anthropic",
          vision: "openai",
        },
        model_params: {
          note_generation: { temperature: 0.1, max_tokens: 2000 },
          vision: {
            temperature: 0.1,
            max_tokens: 500,
            confidence_threshold: "medium",
          },
        },
        pipeline: {
          stage1_skip_window_seconds: 60,
          frame_window_clinic_ms: 3000,
          frame_window_procedural_ms: 7000,
          screen_capture_fps: 2,
          video_capture_fps: 1,
        },
        feature_flags: {
          screen_capture_enabled: true,
          note_versioning_enabled: true,
          session_pause_resume_enabled: true,
          per_session_provider_override: true,
        },
      },
      null,
      2
    );

    const hostedConfigVersion = new appconfig.CfnHostedConfigurationVersion(
      this,
      "AppConfigVersion",
      {
        applicationId: appConfigApp.ref,
        configurationProfileId: appConfigProfile.ref,
        contentType: "application/json",
        content: defaultConfig,
        description: "Initial Aurion configuration",
      }
    );

    // AllAtOnce deployment strategy
    const deploymentStrategy = new appconfig.CfnDeploymentStrategy(
      this,
      "AppConfigDeploymentStrategy",
      {
        name: `aurion-all-at-once-${env}`,
        deploymentDurationInMinutes: 0,
        growthFactor: 100,
        replicateTo: "NONE",
        finalBakeTimeInMinutes: 0,
        growthType: "LINEAR",
        description: "Deploy configuration immediately to all targets",
      }
    );

    const appConfigDeployment = new appconfig.CfnDeployment(
      this,
      "AppConfigDeployment",
      {
        applicationId: appConfigApp.ref,
        environmentId: appConfigEnv.ref,
        configurationProfileId: appConfigProfile.ref,
        configurationVersion: hostedConfigVersion.attrVersionNumber,
        deploymentStrategyId: deploymentStrategy.ref,
        description: "Initial deployment",
      }
    );

    // -----------------------------------------------------------------------
    // CloudWatch — Custom Metrics Namespace & Dashboard
    // -----------------------------------------------------------------------

    const stage1LatencyMetric = new cloudwatch.Metric({
      namespace: `Aurion/${env}`,
      metricName: "Stage1Latency",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
      dimensionsMap: { Service: "note_gen" },
    });

    const stage2LatencyMetric = new cloudwatch.Metric({
      namespace: `Aurion/${env}`,
      metricName: "Stage2Latency",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
      dimensionsMap: { Service: "vision" },
    });

    const maskingPassRateMetric = new cloudwatch.Metric({
      namespace: `Aurion/${env}`,
      metricName: "MaskingPassRate",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
      dimensionsMap: { Service: "masking" },
    });

    const errorRateMetric = new cloudwatch.Metric({
      namespace: `Aurion/${env}`,
      metricName: "ErrorRate",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
      dimensionsMap: { Service: "api" },
    });

    const maskingFailureMetric = new cloudwatch.Metric({
      namespace: `Aurion/${env}`,
      metricName: "MaskingPipelineFailure",
      statistic: "Sum",
      period: cdk.Duration.minutes(1),
      dimensionsMap: { Service: "masking" },
    });

    const consentBlockFailureMetric = new cloudwatch.Metric({
      namespace: `Aurion/${env}`,
      metricName: "ConsentBlockFailure",
      statistic: "Sum",
      period: cdk.Duration.minutes(1),
      dimensionsMap: { Service: "session" },
    });

    const providerFallbackMetric = new cloudwatch.Metric({
      namespace: `Aurion/${env}`,
      metricName: "ProviderFallbackTriggered",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
      dimensionsMap: { Service: "providers" },
    });

    // Dashboard
    const dashboard = new cloudwatch.Dashboard(this, "Dashboard", {
      dashboardName: `Aurion-${env}`,
    });

    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Stage 1 Latency (ms)",
        left: [stage1LatencyMetric],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: "Stage 2 Latency (ms)",
        left: [stage2LatencyMetric],
        width: 12,
      })
    );

    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Masking Pass Rate (%)",
        left: [maskingPassRateMetric],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: "Error Rate",
        left: [errorRateMetric],
        width: 12,
      })
    );

    dashboard.addWidgets(
      new cloudwatch.SingleValueWidget({
        title: "Provider Fallbacks (last hour)",
        metrics: [providerFallbackMetric],
        width: 8,
      }),
      new cloudwatch.SingleValueWidget({
        title: "Masking Failures (last hour)",
        metrics: [maskingFailureMetric],
        width: 8,
      }),
      new cloudwatch.SingleValueWidget({
        title: "Consent Block Failures (last hour)",
        metrics: [consentBlockFailureMetric],
        width: 8,
      })
    );

    // -----------------------------------------------------------------------
    // CloudWatch Alarms
    // -----------------------------------------------------------------------

    new cloudwatch.Alarm(this, "Stage1LatencyAlarm", {
      alarmName: `aurion-${env}-stage1-latency-high`,
      alarmDescription:
        "Stage 1 note generation latency exceeds 60 seconds",
      metric: stage1LatencyMetric,
      threshold: 60000, // 60 seconds in milliseconds
      evaluationPeriods: 3,
      comparisonOperator:
        cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    new cloudwatch.Alarm(this, "MaskingPipelineFailureAlarm", {
      alarmName: `aurion-${env}-masking-failure`,
      alarmDescription:
        "Masking pipeline failure detected — unmasked frame may have been processed",
      metric: maskingFailureMetric,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator:
        cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    new cloudwatch.Alarm(this, "ConsentBlockFailureAlarm", {
      alarmName: `aurion-${env}-consent-block-failure`,
      alarmDescription:
        "Consent block bypassed — recording started without confirmed consent",
      metric: consentBlockFailureMetric,
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator:
        cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    new cloudwatch.Alarm(this, "ProviderFallbackAlarm", {
      alarmName: `aurion-${env}-provider-fallback`,
      alarmDescription:
        "AI provider fallback triggered — primary provider unavailable",
      metric: providerFallbackMetric,
      threshold: 3,
      evaluationPeriods: 1,
      comparisonOperator:
        cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    // -----------------------------------------------------------------------
    // Stack Outputs
    // -----------------------------------------------------------------------

    new cdk.CfnOutput(this, "VpcId", {
      value: vpc.vpcId,
      description: "VPC ID",
    });

    new cdk.CfnOutput(this, "ClusterArn", {
      value: cluster.clusterArn,
      description: "ECS Cluster ARN",
    });

    new cdk.CfnOutput(this, "ApiServiceUrl", {
      value: `http://${apiService.loadBalancer.loadBalancerDnsName}`,
      description: "FastAPI ALB URL",
    });

    new cdk.CfnOutput(this, "DatabaseEndpoint", {
      value: dbInstance.dbInstanceEndpointAddress,
      description: "RDS PostgreSQL endpoint",
    });

    new cdk.CfnOutput(this, "DatabaseSecretArn", {
      value: dbInstance.secret?.secretArn ?? "N/A",
      description: "RDS credentials secret ARN",
    });

    new cdk.CfnOutput(this, "AuditLogTableName", {
      value: auditLogTable.tableName,
      description: "DynamoDB audit log table name",
    });

    new cdk.CfnOutput(this, "AudioBucketName", {
      value: audioBucket.bucketName,
      description: "S3 audio bucket",
    });

    new cdk.CfnOutput(this, "FramesBucketName", {
      value: framesBucket.bucketName,
      description: "S3 frames bucket",
    });

    new cdk.CfnOutput(this, "EvalBucketName", {
      value: evalBucket.bucketName,
      description: "S3 eval bucket",
    });

    new cdk.CfnOutput(this, "UserPoolId", {
      value: userPool.userPoolId,
      description: "Cognito User Pool ID",
    });

    new cdk.CfnOutput(this, "UserPoolClientId", {
      value: userPoolClient.userPoolClientId,
      description: "Cognito User Pool Client ID",
    });

    new cdk.CfnOutput(this, "AppConfigApplicationId", {
      value: appConfigApp.ref,
      description: "AppConfig Application ID",
    });

    new cdk.CfnOutput(this, "AppConfigEnvironmentId", {
      value: appConfigEnv.ref,
      description: "AppConfig Environment ID",
    });

    new cdk.CfnOutput(this, "EncryptionKeyArn", {
      value: encryptionKey.keyArn,
      description: "KMS encryption key ARN",
    });

    new cdk.CfnOutput(this, "DashboardUrl", {
      value: `https://ca-central-1.console.aws.amazon.com/cloudwatch/home?region=ca-central-1#dashboards:name=Aurion-${env}`,
      description: "CloudWatch Dashboard URL",
    });
  }
}
