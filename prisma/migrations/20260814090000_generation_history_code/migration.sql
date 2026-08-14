ALTER TABLE `GenerationTask`
    ADD COLUMN `historyCode` VARCHAR(7) NULL;

SET @history_code_sequence = 1000000;

UPDATE `GenerationTask`
SET `historyCode` = LPAD((@history_code_sequence := @history_code_sequence + 1) - 1, 7, '0')
WHERE `historyCode` IS NULL
ORDER BY `createdAt`, `id`;

CREATE UNIQUE INDEX `GenerationTask_historyCode_key`
    ON `GenerationTask`(`historyCode`);
