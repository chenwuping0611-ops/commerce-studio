-- CreateTable
CREATE TABLE `User` (
    `id` VARCHAR(191) NOT NULL,
    `email` VARCHAR(191) NOT NULL,
    `passwordHash` VARCHAR(191) NOT NULL,
    `displayName` VARCHAR(191) NOT NULL,
    `status` ENUM('ACTIVE', 'DISABLED') NOT NULL DEFAULT 'ACTIVE',
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    UNIQUE INDEX `User_email_key`(`email`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `Role` (
    `id` VARCHAR(191) NOT NULL,
    `code` VARCHAR(191) NOT NULL,
    `name` VARCHAR(191) NOT NULL,
    `description` VARCHAR(191) NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    UNIQUE INDEX `Role_code_key`(`code`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `Permission` (
    `id` VARCHAR(191) NOT NULL,
    `code` VARCHAR(191) NOT NULL,
    `name` VARCHAR(191) NOT NULL,
    `description` VARCHAR(191) NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    UNIQUE INDEX `Permission_code_key`(`code`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `UserRole` (
    `userId` VARCHAR(191) NOT NULL,
    `roleId` VARCHAR(191) NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    INDEX `UserRole_roleId_idx`(`roleId`),
    PRIMARY KEY (`userId`, `roleId`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `RolePermission` (
    `roleId` VARCHAR(191) NOT NULL,
    `permissionId` VARCHAR(191) NOT NULL,

    INDEX `RolePermission_permissionId_idx`(`permissionId`),
    PRIMARY KEY (`roleId`, `permissionId`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `Team` (
    `id` VARCHAR(191) NOT NULL,
    `name` VARCHAR(191) NOT NULL,
    `code` VARCHAR(191) NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    UNIQUE INDEX `Team_code_key`(`code`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `TeamMember` (
    `userId` VARCHAR(191) NOT NULL,
    `teamId` VARCHAR(191) NOT NULL,
    `isLead` BOOLEAN NOT NULL DEFAULT false,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    INDEX `TeamMember_teamId_idx`(`teamId`),
    PRIMARY KEY (`userId`, `teamId`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `Product` (
    `id` VARCHAR(191) NOT NULL,
    `name` VARCHAR(191) NOT NULL,
    `code` VARCHAR(191) NOT NULL,
    `brand` VARCHAR(191) NULL,
    `category` VARCHAR(191) NULL,
    `description` TEXT NULL,
    `status` ENUM('DRAFT', 'ACTIVE', 'ARCHIVED') NOT NULL DEFAULT 'DRAFT',
    `createdById` VARCHAR(191) NOT NULL,
    `ownerId` VARCHAR(191) NULL,
    `teamId` VARCHAR(191) NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    UNIQUE INDEX `Product_code_key`(`code`),
    INDEX `Product_createdById_idx`(`createdById`),
    INDEX `Product_ownerId_idx`(`ownerId`),
    INDEX `Product_teamId_idx`(`teamId`),
    INDEX `Product_status_idx`(`status`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `ProductVariant` (
    `id` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NOT NULL,
    `sku` VARCHAR(191) NOT NULL,
    `name` VARCHAR(191) NULL,
    `color` VARCHAR(191) NULL,
    `size` VARCHAR(191) NULL,
    `material` VARCHAR(191) NULL,
    `status` ENUM('DRAFT', 'ACTIVE', 'ARCHIVED') NOT NULL DEFAULT 'DRAFT',
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    INDEX `ProductVariant_productId_idx`(`productId`),
    UNIQUE INDEX `ProductVariant_productId_sku_key`(`productId`, `sku`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `ProductAsset` (
    `id` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NOT NULL,
    `variantId` VARCHAR(191) NULL,
    `type` VARCHAR(191) NOT NULL,
    `view` VARCHAR(191) NULL,
    `storageKey` VARCHAR(191) NOT NULL,
    `originalName` VARCHAR(191) NULL,
    `mimeType` VARCHAR(191) NOT NULL,
    `byteSize` INTEGER NOT NULL,
    `sha256` VARCHAR(191) NOT NULL,
    `reviewStatus` ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL DEFAULT 'PENDING',
    `createdById` VARCHAR(191) NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    INDEX `ProductAsset_productId_idx`(`productId`),
    INDEX `ProductAsset_variantId_idx`(`variantId`),
    INDEX `ProductAsset_sha256_idx`(`sha256`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `ProductFact` (
    `id` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NOT NULL,
    `key` VARCHAR(191) NOT NULL,
    `value` TEXT NOT NULL,
    `source` VARCHAR(191) NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    INDEX `ProductFact_productId_idx`(`productId`),
    UNIQUE INDEX `ProductFact_productId_key_key`(`productId`, `key`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `BrandMemory` (
    `id` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NOT NULL,
    `key` VARCHAR(191) NOT NULL,
    `value` TEXT NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    INDEX `BrandMemory_productId_idx`(`productId`),
    UNIQUE INDEX `BrandMemory_productId_key_key`(`productId`, `key`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `GenerationRule` (
    `id` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NOT NULL,
    `rule` TEXT NOT NULL,
    `priority` INTEGER NOT NULL DEFAULT 0,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    INDEX `GenerationRule_productId_priority_idx`(`productId`, `priority`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `ForbiddenRule` (
    `id` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NOT NULL,
    `rule` TEXT NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    INDEX `ForbiddenRule_productId_idx`(`productId`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `ProductMemoryVersion` (
    `id` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NOT NULL,
    `version` INTEGER NOT NULL,
    `snapshot` JSON NOT NULL,
    `createdById` VARCHAR(191) NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    INDEX `ProductMemoryVersion_productId_createdAt_idx`(`productId`, `createdAt`),
    UNIQUE INDEX `ProductMemoryVersion_productId_version_key`(`productId`, `version`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `PromptTemplate` (
    `id` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NULL,
    `name` VARCHAR(191) NOT NULL,
    `template` TEXT NOT NULL,
    `createdById` VARCHAR(191) NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    INDEX `PromptTemplate_productId_idx`(`productId`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `PromptVersion` (
    `id` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NULL,
    `templateId` VARCHAR(191) NULL,
    `version` INTEGER NOT NULL,
    `promptText` TEXT NOT NULL,
    `systemText` TEXT NULL,
    `metadata` JSON NULL,
    `createdById` VARCHAR(191) NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    INDEX `PromptVersion_productId_createdAt_idx`(`productId`, `createdAt`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `PromptExecution` (
    `id` VARCHAR(191) NOT NULL,
    `promptVersionId` VARCHAR(191) NOT NULL,
    `taskId` VARCHAR(191) NULL,
    `input` JSON NOT NULL,
    `output` JSON NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    INDEX `PromptExecution_promptVersionId_idx`(`promptVersionId`),
    INDEX `PromptExecution_taskId_idx`(`taskId`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `ModelProvider` (
    `id` VARCHAR(191) NOT NULL,
    `name` VARCHAR(191) NOT NULL,
    `kind` ENUM('NATIVE', 'OPENAI_COMPATIBLE') NOT NULL,
    `baseUrl` VARCHAR(191) NOT NULL,
    `apiKeyEncrypted` TEXT NOT NULL,
    `apiKeyHint` VARCHAR(191) NULL,
    `enabled` BOOLEAN NOT NULL DEFAULT true,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    UNIQUE INDEX `ModelProvider_name_key`(`name`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `ModelProfile` (
    `id` VARCHAR(191) NOT NULL,
    `providerId` VARCHAR(191) NOT NULL,
    `name` VARCHAR(191) NOT NULL,
    `capability` JSON NOT NULL,
    `endpointPath` VARCHAR(191) NULL,
    `enabled` BOOLEAN NOT NULL DEFAULT true,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    INDEX `ModelProfile_providerId_idx`(`providerId`),
    UNIQUE INDEX `ModelProfile_providerId_name_key`(`providerId`, `name`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `GenerationTask` (
    `id` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NOT NULL,
    `variantId` VARCHAR(191) NULL,
    `createdById` VARCHAR(191) NOT NULL,
    `providerId` VARCHAR(191) NOT NULL,
    `modelProfileId` VARCHAR(191) NOT NULL,
    `type` ENUM('IMAGE', 'VIDEO') NOT NULL,
    `status` ENUM('CREATED', 'QUEUED', 'RUNNING', 'PROVIDER_SUBMITTED', 'PROVIDER_PROCESSING', 'SUCCEEDED', 'FAILED', 'RETRY_WAITING', 'CANCEL_REQUESTED', 'CANCELLED', 'EXPIRED') NOT NULL DEFAULT 'CREATED',
    `idea` TEXT NOT NULL,
    `promptSnapshot` JSON NOT NULL,
    `memorySnapshot` JSON NOT NULL,
    `inputAssets` JSON NULL,
    `output` JSON NULL,
    `providerTaskId` VARCHAR(191) NULL,
    `retryCount` INTEGER NOT NULL DEFAULT 0,
    `maxRetries` INTEGER NOT NULL DEFAULT 2,
    `leaseUntil` DATETIME(3) NULL,
    `heartbeatAt` DATETIME(3) NULL,
    `nextPollAt` DATETIME(3) NULL,
    `errorCode` VARCHAR(191) NULL,
    `errorSummary` TEXT NULL,
    `idempotencyKey` VARCHAR(191) NULL,
    `completedAt` DATETIME(3) NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    INDEX `GenerationTask_status_nextPollAt_idx`(`status`, `nextPollAt`),
    INDEX `GenerationTask_createdById_createdAt_idx`(`createdById`, `createdAt`),
    INDEX `GenerationTask_productId_createdAt_idx`(`productId`, `createdAt`),
    UNIQUE INDEX `GenerationTask_createdById_idempotencyKey_key`(`createdById`, `idempotencyKey`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `GenerationAttempt` (
    `id` VARCHAR(191) NOT NULL,
    `taskId` VARCHAR(191) NOT NULL,
    `attempt` INTEGER NOT NULL,
    `providerTaskId` VARCHAR(191) NULL,
    `request` JSON NULL,
    `response` JSON NULL,
    `status` ENUM('CREATED', 'QUEUED', 'RUNNING', 'PROVIDER_SUBMITTED', 'PROVIDER_PROCESSING', 'SUCCEEDED', 'FAILED', 'RETRY_WAITING', 'CANCEL_REQUESTED', 'CANCELLED', 'EXPIRED') NOT NULL,
    `errorCode` VARCHAR(191) NULL,
    `errorSummary` TEXT NULL,
    `startedAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `finishedAt` DATETIME(3) NULL,

    INDEX `GenerationAttempt_taskId_idx`(`taskId`),
    UNIQUE INDEX `GenerationAttempt_taskId_attempt_key`(`taskId`, `attempt`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `GenerationAsset` (
    `id` VARCHAR(191) NOT NULL,
    `taskId` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NOT NULL,
    `storageKey` VARCHAR(191) NOT NULL,
    `originalName` VARCHAR(191) NULL,
    `mimeType` VARCHAR(191) NOT NULL,
    `byteSize` INTEGER NOT NULL,
    `sha256` VARCHAR(191) NOT NULL,
    `sourceUrl` VARCHAR(191) NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    INDEX `GenerationAsset_taskId_idx`(`taskId`),
    INDEX `GenerationAsset_productId_idx`(`productId`),
    INDEX `GenerationAsset_sha256_idx`(`sha256`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `CostLedger` (
    `id` VARCHAR(191) NOT NULL,
    `taskId` VARCHAR(191) NOT NULL,
    `providerId` VARCHAR(191) NOT NULL,
    `modelProfileId` VARCHAR(191) NOT NULL,
    `currency` VARCHAR(191) NOT NULL DEFAULT 'USD',
    `amount` DECIMAL(12, 6) NOT NULL,
    `usage` JSON NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    UNIQUE INDEX `CostLedger_taskId_key`(`taskId`),
    INDEX `CostLedger_providerId_createdAt_idx`(`providerId`, `createdAt`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `CanvasDocument` (
    `id` VARCHAR(191) NOT NULL,
    `name` VARCHAR(191) NOT NULL,
    `productId` VARCHAR(191) NULL,
    `teamId` VARCHAR(191) NULL,
    `createdById` VARCHAR(191) NOT NULL,
    `version` INTEGER NOT NULL DEFAULT 1,
    `nodes` JSON NOT NULL,
    `edges` JSON NOT NULL,
    `viewport` JSON NOT NULL,
    `settings` JSON NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    INDEX `CanvasDocument_createdById_idx`(`createdById`),
    INDEX `CanvasDocument_teamId_idx`(`teamId`),
    INDEX `CanvasDocument_productId_idx`(`productId`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `CanvasRevision` (
    `id` VARCHAR(191) NOT NULL,
    `canvasId` VARCHAR(191) NOT NULL,
    `version` INTEGER NOT NULL,
    `nodes` JSON NOT NULL,
    `edges` JSON NOT NULL,
    `viewport` JSON NOT NULL,
    `summary` VARCHAR(191) NULL,
    `createdById` VARCHAR(191) NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    INDEX `CanvasRevision_canvasId_idx`(`canvasId`),
    UNIQUE INDEX `CanvasRevision_canvasId_version_key`(`canvasId`, `version`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `CanvasExecution` (
    `id` VARCHAR(191) NOT NULL,
    `canvasId` VARCHAR(191) NOT NULL,
    `version` INTEGER NOT NULL,
    `snapshot` JSON NOT NULL,
    `taskIds` JSON NULL,
    `status` ENUM('CREATED', 'QUEUED', 'RUNNING', 'PROVIDER_SUBMITTED', 'PROVIDER_PROCESSING', 'SUCCEEDED', 'FAILED', 'RETRY_WAITING', 'CANCEL_REQUESTED', 'CANCELLED', 'EXPIRED') NOT NULL DEFAULT 'CREATED',
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    INDEX `CanvasExecution_canvasId_createdAt_idx`(`canvasId`, `createdAt`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `AuditLog` (
    `id` VARCHAR(191) NOT NULL,
    `actorId` VARCHAR(191) NULL,
    `action` VARCHAR(191) NOT NULL,
    `resource` VARCHAR(191) NOT NULL,
    `resourceId` VARCHAR(191) NULL,
    `requestId` VARCHAR(191) NULL,
    `metadata` JSON NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    INDEX `AuditLog_actorId_createdAt_idx`(`actorId`, `createdAt`),
    INDEX `AuditLog_resource_resourceId_idx`(`resource`, `resourceId`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `SystemSetting` (
    `id` VARCHAR(191) NOT NULL,
    `key` VARCHAR(191) NOT NULL,
    `value` JSON NOT NULL,
    `isSecret` BOOLEAN NOT NULL DEFAULT false,
    `updatedAt` DATETIME(3) NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),

    UNIQUE INDEX `SystemSetting_key_key`(`key`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- AddForeignKey
ALTER TABLE `UserRole` ADD CONSTRAINT `UserRole_userId_fkey` FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `UserRole` ADD CONSTRAINT `UserRole_roleId_fkey` FOREIGN KEY (`roleId`) REFERENCES `Role`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `RolePermission` ADD CONSTRAINT `RolePermission_roleId_fkey` FOREIGN KEY (`roleId`) REFERENCES `Role`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `RolePermission` ADD CONSTRAINT `RolePermission_permissionId_fkey` FOREIGN KEY (`permissionId`) REFERENCES `Permission`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `TeamMember` ADD CONSTRAINT `TeamMember_userId_fkey` FOREIGN KEY (`userId`) REFERENCES `User`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `TeamMember` ADD CONSTRAINT `TeamMember_teamId_fkey` FOREIGN KEY (`teamId`) REFERENCES `Team`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `Product` ADD CONSTRAINT `Product_createdById_fkey` FOREIGN KEY (`createdById`) REFERENCES `User`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `Product` ADD CONSTRAINT `Product_ownerId_fkey` FOREIGN KEY (`ownerId`) REFERENCES `User`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `Product` ADD CONSTRAINT `Product_teamId_fkey` FOREIGN KEY (`teamId`) REFERENCES `Team`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ProductVariant` ADD CONSTRAINT `ProductVariant_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ProductAsset` ADD CONSTRAINT `ProductAsset_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ProductAsset` ADD CONSTRAINT `ProductAsset_variantId_fkey` FOREIGN KEY (`variantId`) REFERENCES `ProductVariant`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ProductFact` ADD CONSTRAINT `ProductFact_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `BrandMemory` ADD CONSTRAINT `BrandMemory_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `GenerationRule` ADD CONSTRAINT `GenerationRule_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ForbiddenRule` ADD CONSTRAINT `ForbiddenRule_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ProductMemoryVersion` ADD CONSTRAINT `ProductMemoryVersion_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ProductMemoryVersion` ADD CONSTRAINT `ProductMemoryVersion_createdById_fkey` FOREIGN KEY (`createdById`) REFERENCES `User`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `PromptTemplate` ADD CONSTRAINT `PromptTemplate_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `PromptVersion` ADD CONSTRAINT `PromptVersion_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `PromptVersion` ADD CONSTRAINT `PromptVersion_templateId_fkey` FOREIGN KEY (`templateId`) REFERENCES `PromptTemplate`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `PromptVersion` ADD CONSTRAINT `PromptVersion_createdById_fkey` FOREIGN KEY (`createdById`) REFERENCES `User`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `PromptExecution` ADD CONSTRAINT `PromptExecution_promptVersionId_fkey` FOREIGN KEY (`promptVersionId`) REFERENCES `PromptVersion`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `PromptExecution` ADD CONSTRAINT `PromptExecution_taskId_fkey` FOREIGN KEY (`taskId`) REFERENCES `GenerationTask`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `ModelProfile` ADD CONSTRAINT `ModelProfile_providerId_fkey` FOREIGN KEY (`providerId`) REFERENCES `ModelProvider`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `GenerationTask` ADD CONSTRAINT `GenerationTask_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `GenerationTask` ADD CONSTRAINT `GenerationTask_variantId_fkey` FOREIGN KEY (`variantId`) REFERENCES `ProductVariant`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `GenerationTask` ADD CONSTRAINT `GenerationTask_createdById_fkey` FOREIGN KEY (`createdById`) REFERENCES `User`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `GenerationTask` ADD CONSTRAINT `GenerationTask_providerId_fkey` FOREIGN KEY (`providerId`) REFERENCES `ModelProvider`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `GenerationTask` ADD CONSTRAINT `GenerationTask_modelProfileId_fkey` FOREIGN KEY (`modelProfileId`) REFERENCES `ModelProfile`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `GenerationAttempt` ADD CONSTRAINT `GenerationAttempt_taskId_fkey` FOREIGN KEY (`taskId`) REFERENCES `GenerationTask`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `GenerationAsset` ADD CONSTRAINT `GenerationAsset_taskId_fkey` FOREIGN KEY (`taskId`) REFERENCES `GenerationTask`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `GenerationAsset` ADD CONSTRAINT `GenerationAsset_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `CostLedger` ADD CONSTRAINT `CostLedger_taskId_fkey` FOREIGN KEY (`taskId`) REFERENCES `GenerationTask`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `CanvasDocument` ADD CONSTRAINT `CanvasDocument_productId_fkey` FOREIGN KEY (`productId`) REFERENCES `Product`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `CanvasDocument` ADD CONSTRAINT `CanvasDocument_teamId_fkey` FOREIGN KEY (`teamId`) REFERENCES `Team`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `CanvasDocument` ADD CONSTRAINT `CanvasDocument_createdById_fkey` FOREIGN KEY (`createdById`) REFERENCES `User`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `CanvasRevision` ADD CONSTRAINT `CanvasRevision_canvasId_fkey` FOREIGN KEY (`canvasId`) REFERENCES `CanvasDocument`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `CanvasExecution` ADD CONSTRAINT `CanvasExecution_canvasId_fkey` FOREIGN KEY (`canvasId`) REFERENCES `CanvasDocument`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `AuditLog` ADD CONSTRAINT `AuditLog_actorId_fkey` FOREIGN KEY (`actorId`) REFERENCES `User`(`id`) ON DELETE SET NULL ON UPDATE CASCADE;
