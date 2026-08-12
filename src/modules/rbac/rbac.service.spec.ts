import { RbacService } from "./rbac.service";

describe("RbacService", () => {
  const service = new RbacService();

  it("grants every permission to super admins", () => {
    expect(
      service.hasPermission(
        {
          id: "admin",
          email: "admin@example.com",
          displayName: "Admin",
          roles: ["super_admin"],
          teamIds: [],
          permissions: [],
        },
        "anything:read:system",
      ),
    ).toBe(true);
  });

  it("requires an explicit permission for regular users", () => {
    const user = {
      id: "employee",
      email: "employee@example.com",
      displayName: "Employee",
      roles: ["employee"],
      teamIds: ["team-1"],
      permissions: ["product:read:team"],
    };
    expect(service.hasPermission(user, "product:read:team")).toBe(true);
    expect(service.hasPermission(user, "model_config:read:system")).toBe(false);
  });
});
