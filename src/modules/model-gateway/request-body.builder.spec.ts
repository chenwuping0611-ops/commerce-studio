import { buildConfiguredRequestBody } from "./request-body.builder";

describe("buildConfiguredRequestBody", () => {
  const request = {
    type: "IMAGE",
    provider: {} as any,
    model: { name: "gpt-image-2" } as any,
    prompt: "保留主体结构，改成赛博朋克风格",
    options: {
      count: 1,
      aspectRatio: "1:1",
      resolution: "1k",
    },
    idempotencyKey: "task-123",
  } as any;

  it("composes an image body with runtime values and keeps arrays typed", () => {
    expect(
      buildConfiguredRequestBody(
        request,
        [
          { field: "model", value: "{{model}}", valueType: "string" },
          { field: "prompt", value: "{{prompt}}", valueType: "string" },
          { field: "n", value: "{{count}}", valueType: "number" },
          { field: "size", value: "{{size}}", valueType: "string" },
          { field: "resolution", value: "{{resolution}}", valueType: "string" },
          { field: "image_urls", value: "{{image_urls}}", valueType: "string" },
          { field: "response_format", value: "url", valueType: "string" },
        ],
        ["https://example.com/source.png"],
      ),
    ).toEqual({
      model: "gpt-image-2",
      prompt: "保留主体结构，改成赛博朋克风格",
      n: 1,
      size: "1:1",
      resolution: "1k",
      image_urls: ["https://example.com/source.png"],
      response_format: "url",
    });
  });

  it("omits empty or unavailable values instead of sending null-like fields", () => {
    expect(
      buildConfiguredRequestBody(
        {
          ...request,
          options: {},
        },
        [
          { field: "model", value: "{{model}}", valueType: "string" },
          { field: "resolution", value: "", valueType: "string" },
          { field: "generate_audio", value: "", valueType: "boolean" },
          {
            field: "custom",
            value: "{{options.unknown}}",
            valueType: "string",
          },
        ],
        [],
      ),
    ).toEqual({ model: "gpt-image-2" });
  });

  it("keeps video reference roles separate from image URL arrays", () => {
    expect(
      buildConfiguredRequestBody(
        {
          ...request,
          type: "VIDEO",
          model: { name: "seedance-2" },
          options: { duration: 5, aspectRatio: "16:9" },
        },
        [
          { field: "model", value: "{{model}}", valueType: "string" },
          { field: "prompt", value: "{{prompt}}", valueType: "string" },
          { field: "duration", value: "{{duration}}", valueType: "number" },
          {
            field: "image_with_roles",
            value: "{{image_with_roles}}",
            valueType: "json",
          },
        ],
        ["https://example.com/source.png"],
      ),
    ).toEqual({
      model: "seedance-2",
      prompt: "保留主体结构，改成赛博朋克风格",
      duration: 5,
      image_with_roles: [
        {
          url: "https://example.com/source.png",
          role: "reference_image",
        },
      ],
    });
  });
});
