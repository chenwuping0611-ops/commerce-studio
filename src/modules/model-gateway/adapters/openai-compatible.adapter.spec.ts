import { OpenAiCompatibleAdapter } from "./openai-compatible.adapter";

describe("OpenAiCompatibleAdapter", () => {
  const config = {
    get: jest.fn((_key: string, fallback: number) => fallback),
  };
  const encryption = {
    decrypt: jest.fn(() => "sk-test"),
  };

  const provider = {
    baseUrl: "https://toapis.com/v1",
    apiKeyEncrypted: "encrypted",
  } as any;

  const imageRequest = {
    provider,
    model: {
      name: "gpt-image-2",
      endpointPath: "/images/generations",
    },
    type: "IMAGE",
    prompt: "product studio photo",
    inputAssets: ["https://example.com/product.png"],
    options: {
      count: 1,
      aspectRatio: "1:1",
    },
    idempotencyKey: "task-image-1",
  } as any;

  const videoRequest = {
    provider,
    model: {
      name: "seedance-2",
      endpointPath: "/videos/generations",
    },
    type: "VIDEO",
    prompt: "product commercial",
    inputAssets: ["https://example.com/product.png"],
    options: {
      duration: 5,
      aspectRatio: "16:9",
      resolution: "720p",
      generateAudio: false,
    },
    idempotencyKey: "task-video-1",
  } as any;

  beforeEach(() => {
    jest.restoreAllMocks();
  });

  it("builds the documented gpt-image-2 request body", async () => {
    const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "task_img_1",
          object: "generation.task",
          model: "gpt-image-2",
          status: "queued",
          progress: 0,
        }),
        { status: 200 },
      ),
    );
    const adapter = new OpenAiCompatibleAdapter(
      encryption as any,
      config as any,
    );

    await adapter.submit(imageRequest);

    const [url, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(String((init as RequestInit).body));
    expect(url).toBe("https://toapis.com/v1/images/generations");
    expect(body).toMatchObject({
      model: "gpt-image-2",
      prompt: "product studio photo",
      n: 1,
      size: "1:1",
      resolution: "1k",
      response_format: "url",
      reference_images: ["https://example.com/product.png"],
      client_business_id: "task-image-1",
    });
    expect(body.image_urls).toBeUndefined();
  });

  it("maps seedance-2 product references to image_with_roles", async () => {
    const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "task_vid_1",
          object: "generation.task",
          model: "seedance-2",
          status: "in_progress",
          progress: 10,
        }),
        { status: 200 },
      ),
    );
    const adapter = new OpenAiCompatibleAdapter(
      encryption as any,
      config as any,
    );

    await adapter.submit(videoRequest);

    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse(String((init as RequestInit).body));
    expect(body).toMatchObject({
      model: "seedance-2",
      duration: 5,
      aspect_ratio: "16:9",
      resolution: "720p",
      generate_audio: false,
      image_with_roles: [
        {
          url: "https://example.com/product.png",
          role: "reference_image",
        },
      ],
    });
    expect(body.image_urls).toBeUndefined();
  });

  it("uploads local reference images before sending them to ToAPIs", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(
        new Response(Buffer.from([137, 80, 78, 71]), {
          status: 200,
          headers: { "content-type": "image/png" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            success: true,
            data: { url: "https://files.toapis.com/reference/uploaded.png" },
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "task_img_local_1",
            object: "generation.task",
            model: "gpt-image-2",
            status: "queued",
          }),
          { status: 200 },
        ),
      );
    const adapter = new OpenAiCompatibleAdapter(
      encryption as any,
      config as any,
    );

    await adapter.submit({
      ...imageRequest,
      inputAssets: ["http://127.0.0.1:3000/media/provider/product/asset"],
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const [uploadUrl, uploadInit] = fetchMock.mock.calls[1];
    expect(uploadUrl).toBe("https://toapis.com/v1/uploads/images");
    expect((uploadInit as RequestInit).method).toBe("POST");
    expect((uploadInit as RequestInit).body).toBeInstanceOf(FormData);

    const [, generationInit] = fetchMock.mock.calls[2];
    const generationBody = JSON.parse(
      String((generationInit as RequestInit).body),
    );
    expect(generationBody.reference_images).toEqual([
      "https://files.toapis.com/reference/uploaded.png",
    ]);
  });

  it("keeps polling on provider rate limits and honors Retry-After", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: 429,
            message: "rate limited",
          },
        }),
        {
          status: 429,
          headers: { "Retry-After": "7" },
        },
      ),
    );
    const adapter = new OpenAiCompatibleAdapter(
      encryption as any,
      config as any,
    );

    const result = await adapter.poll(videoRequest, "task_vid_1");

    expect(result.status).toBe("processing");
    expect(result.retryAfterMs).toBe(7000);
  });

  it("extracts ToAPIs result.data output when a task completes", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "task_img_1",
          status: "completed",
          result: {
            type: "image",
            data: [{ url: "https://files.toapis.com/generated/image.jpg" }],
          },
        }),
        { status: 200 },
      ),
    );
    const adapter = new OpenAiCompatibleAdapter(
      encryption as any,
      config as any,
    );

    const result = await adapter.poll(imageRequest, "task_img_1");

    expect(result.status).toBe("succeeded");
    expect(result.output).toEqual({
      type: "image",
      data: [{ url: "https://files.toapis.com/generated/image.jpg" }],
    });
  });
});
