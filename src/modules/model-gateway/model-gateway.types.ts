import type {
  GenerationType,
  ModelProfile,
  ModelProvider,
} from "@prisma/client";

export type ModelRequestParameterType =
  | "string"
  | "number"
  | "boolean"
  | "json";

export interface ModelRequestParameter {
  field: string;
  value: unknown;
  valueType?: ModelRequestParameterType;
  enabled?: boolean;
  description?: string;
}

export interface ModelRequestParameters {
  image?: ModelRequestParameter[];
  video?: ModelRequestParameter[];
}

export interface ProviderGenerationRequest {
  type: GenerationType;
  model: ModelProfile;
  provider: ModelProvider;
  prompt: string;
  negativePrompt?: string;
  inputAssets?: string[];
  options?: Record<string, unknown>;
  idempotencyKey?: string;
}

export interface ProviderSubmission {
  providerTaskId: string;
  status: "submitted" | "processing" | "succeeded";
  output?: Record<string, unknown>;
  raw?: Record<string, unknown>;
}

export interface ProviderPollResult {
  status: "processing" | "succeeded" | "failed";
  output?: Record<string, unknown>;
  raw?: Record<string, unknown>;
  errorCode?: string;
  errorSummary?: string;
  retryAfterMs?: number;
}

export interface ModelProviderAdapter {
  submit(request: ProviderGenerationRequest): Promise<ProviderSubmission>;
  poll(
    request: ProviderGenerationRequest,
    providerTaskId: string,
  ): Promise<ProviderPollResult>;
  cancel?(
    request: ProviderGenerationRequest,
    providerTaskId: string,
  ): Promise<void>;
}
