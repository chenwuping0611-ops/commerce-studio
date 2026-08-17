import { AppError } from "../../common/errors/app-error";
import type {
  ModelRequestParameter,
  ProviderGenerationRequest,
} from "./model-gateway.types";

/**
 * Build a provider JSON body from the model profile's media-specific
 * parameter list. The function is intentionally pure so image/video request
 * composition can be tested without a live provider.
 */
export function buildConfiguredRequestBody(
  request: ProviderGenerationRequest,
  parameters: ModelRequestParameter[],
  referenceImages: string[],
) {
  const body: Record<string, unknown> = {};
  for (const parameter of parameters) {
    if (!parameter || parameter.enabled === false) continue;
    const value = resolveConfiguredParameter(
      parameter,
      request,
      referenceImages,
    );
    if (value !== undefined) {
      body[parameter.field] = value;
    }
  }
  return body;
}

function resolveConfiguredParameter(
  parameter: ModelRequestParameter,
  request: ProviderGenerationRequest,
  referenceImages: string[],
) {
  const rawValue = parameter.value;
  if (rawValue === undefined || rawValue === null) return undefined;

  if (typeof rawValue !== "string") {
    return normalizeTypedValue(parameter, rawValue);
  }

  const value = rawValue.trim();
  if (!value) return undefined;

  const runtimeValue = resolveRuntimeValue(value, request, referenceImages);
  if (runtimeValue !== undefined) return runtimeValue;
  if (/^\{\{[^{}]+\}\}$/.test(value)) return undefined;
  return normalizeTypedValue(parameter, value);
}

function normalizeTypedValue(parameter: ModelRequestParameter, value: unknown) {
  switch (parameter.valueType) {
    case "number": {
      const number = typeof value === "number" ? value : Number(value);
      return Number.isFinite(number) ? number : undefined;
    }
    case "boolean":
      if (typeof value === "boolean") return value;
      if (value === "true") return true;
      if (value === "false") return false;
      return undefined;
    case "json":
      if (typeof value !== "string") return value;
      try {
        return JSON.parse(value);
      } catch {
        throw new AppError(
          "MODEL_REQUEST_PARAMETER_VALUE_INVALID",
          `请求字段 ${parameter.field} 的 JSON 值无效`,
          400,
        );
      }
    case "string":
    default:
      return typeof value === "string" ? value : value;
  }
}

function resolveRuntimeValue(
  value: string,
  request: ProviderGenerationRequest,
  referenceImages: string[],
) {
  const options = request.options ?? {};
  switch (value) {
    case "{{model}}":
      return request.model.name || undefined;
    case "{{prompt}}":
      return request.prompt || undefined;
    case "{{negative_prompt}}":
      return request.negativePrompt || undefined;
    case "{{count}}":
    case "{{n}}":
      return options.count === undefined
        ? undefined
        : positiveInteger(options.count, 1);
    case "{{duration}}":
      return options.duration === undefined
        ? undefined
        : positiveInteger(options.duration, 1);
    case "{{aspect_ratio}}":
    case "{{size}}":
      return nonEmptyString(options.aspectRatio);
    case "{{resolution}}":
      return nonEmptyString(options.resolution);
    case "{{response_format}}":
      return nonEmptyString(options.responseFormat);
    case "{{generate_audio}}":
      return typeof options.generateAudio === "boolean"
        ? options.generateAudio
        : undefined;
    case "{{return_last_frame}}":
      return typeof options.returnLastFrame === "boolean"
        ? options.returnLastFrame
        : undefined;
    case "{{idempotency_key}}":
    case "{{client_business_id}}":
      return request.idempotencyKey || undefined;
    case "{{reference_images}}":
    case "{{image_urls}}":
    case "{{input_assets}}":
      return referenceImages.length ? referenceImages : undefined;
    case "{{image_with_roles}}":
      return referenceImages.length
        ? referenceImages.map((url) => ({
            url,
            role: "reference_image",
          }))
        : undefined;
    default:
      return resolveRuntimeOption(value, options);
  }
}

function resolveRuntimeOption(value: string, options: Record<string, unknown>) {
  const match = value.match(
    /^\{\{(?:option|options)\.([A-Za-z][A-Za-z0-9_.-]*)\}\}$/,
  );
  if (!match) return undefined;
  return options[match[1]];
}

function nonEmptyString(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function positiveInteger(value: unknown, fallback: number) {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isInteger(number) && number > 0 ? number : fallback;
}
