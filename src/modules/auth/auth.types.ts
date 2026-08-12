export interface AuthenticatedUser {
  id: string;
  email: string;
  displayName: string;
  roles: string[];
  teamIds: string[];
  permissions: string[];
}

export interface AccessTokenPayload {
  sub: string;
  email: string;
  roles: string[];
  iat?: number;
  exp?: number;
}
