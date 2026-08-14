CREATE TABLE `SkillProfile` (
    `id` VARCHAR(191) NOT NULL,
    `name` VARCHAR(120) NOT NULL,
    `code` VARCHAR(120) NOT NULL,
    `mediaType` VARCHAR(16) NOT NULL,
    `description` TEXT NULL,
    `version` VARCHAR(40) NULL,
    `tags` JSON NULL,
    `promptTemplate` TEXT NULL,
    `negativePrompt` TEXT NULL,
    `settings` JSON NULL,
    `enabled` BOOLEAN NOT NULL DEFAULT true,
    `createdById` VARCHAR(191) NOT NULL,
    `createdAt` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    `updatedAt` DATETIME(3) NOT NULL,

    UNIQUE INDEX `SkillProfile_code_key`(`code`),
    INDEX `SkillProfile_mediaType_enabled_idx`(`mediaType`, `enabled`),
    INDEX `SkillProfile_createdById_createdAt_idx`(`createdById`, `createdAt`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE `SkillProfile`
    ADD CONSTRAINT `SkillProfile_createdById_fkey`
    FOREIGN KEY (`createdById`) REFERENCES `User`(`id`)
    ON DELETE RESTRICT ON UPDATE CASCADE;
