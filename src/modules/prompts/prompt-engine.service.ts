import { Injectable } from "@nestjs/common";

import type { AuthenticatedUser } from "../auth/auth.types";
import { ProductMemoryService } from "../product-memory/product-memory.service";
import { SkillsService } from "../skills/skills.service";
import { CompilePromptDto } from "./dto/compile-prompt.dto";

@Injectable()
export class PromptEngineService {
  constructor(
    private readonly memory: ProductMemoryService,
    private readonly skills: SkillsService,
  ) {}

  /**
   * 目的：把产品记忆、禁止规则和用户创意编译为可审查的 Prompt 快照。
   * 输入：产品、当前用户、创意和生成类型。
   * 输出：系统指令、用户 Prompt、负向约束和记忆版本。
   * 业务规则：禁止规则优先于产品事实、品牌视觉和用户创意。
   * 外部副作用：无。
   */
  async compile(
    user: AuthenticatedUser,
    productId: string,
    dto: CompilePromptDto,
  ) {
    const snapshot = await this.memory.latestSnapshot(user, productId);
    const type = dto.type ?? "IMAGE";
    const skill = dto.skillId
      ? await this.skills.getForGeneration(user, dto.skillId, type)
      : null;
    const systemText = [
      "你是电商产品视觉生成助手。",
      "必须保持产品真实结构、材质、颜色和品牌识别特征。",
      "不得擅自增加未授权的品牌、Logo、功能和配件。",
      `生成类型：${type === "VIDEO" ? "产品广告视频" : "产品图片"}`,
    ].join("\n");
    const promptText = [
      `用户创意：${dto.idea.trim()}`,
      `产品事实：${snapshot.facts.join("；") || "未填写"}`,
      `品牌视觉：${snapshot.brandVisual.join("；") || "未填写"}`,
      `生成规则：${snapshot.generationRules.join("；") || "遵循产品真实信息"}`,
      dto.aspectRatio ? `画幅：${dto.aspectRatio}` : "",
      skill?.promptTemplate ? `Skill 指令：${skill.promptTemplate}` : "",
      "画面要求：商业级电商视觉，主体清晰，产品细节真实，构图适合电商展示。",
    ]
      .filter(Boolean)
      .join("\n");
    return {
      data: {
        type,
        systemText,
        promptText,
        negativePrompt:
          [snapshot.forbiddenRules.join("；"), skill?.negativePrompt ?? ""]
            .filter(Boolean)
            .join("；") || "禁止改变产品结构、品牌标识和核心颜色",
        memoryVersion: snapshot.version,
        skill: skill
          ? {
              id: skill.id,
              name: skill.name,
              code: skill.code,
              version: skill.version,
            }
          : null,
      },
    };
  }
}
