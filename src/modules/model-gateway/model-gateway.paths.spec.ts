import { ModelGatewayService } from "./model-gateway.service";

describe("ModelGatewayService provider paths", () => {
  it("adds the ToAPIs v1 prefix when the configured base URL has no version", () => {
    const service = Object.create(
      ModelGatewayService.prototype,
    ) as ModelGatewayService;

    expect(
      (service as any).providerRelativePath(
        { baseUrl: "https://toapis.com" },
        "/user/balance",
      ),
    ).toBe("/v1/user/balance");
  });

  it("does not duplicate the v1 prefix for a versioned ToAPIs base URL", () => {
    const service = Object.create(
      ModelGatewayService.prototype,
    ) as ModelGatewayService;

    expect(
      (service as any).providerRelativePath(
        { baseUrl: "https://toapis.com/v1" },
        "/user/balance",
      ),
    ).toBe("/user/balance");
  });
});
