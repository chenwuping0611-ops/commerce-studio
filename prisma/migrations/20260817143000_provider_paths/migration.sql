ALTER TABLE `ModelProvider`
  ADD COLUMN `modelsPath` VARCHAR(240) NULL,
  ADD COLUMN `balancePath` VARCHAR(240) NULL;

UPDATE `ModelProvider`
SET
  `modelsPath` = COALESCE(`modelsPath`, '/models'),
  `balancePath` = COALESCE(
    `balancePath`,
    CASE
      WHEN `kind` = 'OPENAI_COMPATIBLE' THEN '/user/balance'
      ELSE '/balance'
    END
  );
