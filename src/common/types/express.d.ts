import type { AuthenticatedUser } from "../../modules/auth/auth.types";

declare global {
  namespace Express {
    interface Request {
      requestId?: string;
      user?: AuthenticatedUser;
    }
  }
}

export {};
