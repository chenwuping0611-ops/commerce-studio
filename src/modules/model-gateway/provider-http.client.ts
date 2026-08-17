import { spawn } from "node:child_process";

const WINDOWS_HTTP_SCRIPT = `
$ProgressPreference = "SilentlyContinue"
$encoded = [Console]::In.ReadToEnd().Trim()
if (-not $encoded) {
  throw "empty request"
}
$json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
$request = $json | ConvertFrom-Json
$httpRequest = [Net.HttpWebRequest]::Create([string]$request.url)
$httpRequest.Method = [string]$request.method
$httpRequest.Timeout = [int]$request.timeoutMs
$httpRequest.ReadWriteTimeout = [int]$request.timeoutMs
$httpRequest.AllowAutoRedirect = $true
foreach ($property in $request.headers.psobject.Properties) {
  $name = [string]$property.Name
  $value = [string]$property.Value
  switch ($name.ToLowerInvariant()) {
    "accept" { $httpRequest.Accept = $value; break }
    "user-agent" { $httpRequest.UserAgent = $value; break }
    "content-type" { $httpRequest.ContentType = $value; break }
    "authorization" {
      $httpRequest.Headers["Authorization"] = $value
      break
    }
    default { $httpRequest.Headers[$name] = $value }
  }
}
if ($null -ne $request.body) {
  $bytes = [Text.Encoding]::UTF8.GetBytes([string]$request.body)
  $httpRequest.ContentLength = $bytes.Length
  $stream = $httpRequest.GetRequestStream()
  $stream.Write($bytes, 0, $bytes.Length)
  $stream.Dispose()
}
$response = $null
try {
  $response = $httpRequest.GetResponse()
} catch [Net.WebException] {
  $response = $_.Exception.Response
  if ($null -eq $response) { throw }
}
$responseStream = $response.GetResponseStream()
$reader = [IO.BinaryReader]::new($responseStream)
$bytes = $reader.ReadBytes(104857600)
$reader.Dispose()
$responseStream.Dispose()
$responseHeaders = @{}
foreach ($name in $response.Headers.AllKeys) {
  $responseHeaders[$name] = [string]$response.Headers[$name]
}
[pscustomobject]@{
  status = [int]$response.StatusCode
  headers = $responseHeaders
  bodyBase64 = [Convert]::ToBase64String($bytes)
} | ConvertTo-Json -Compress -Depth 6
`;

type ProviderRequest = {
  url: string;
  method: string;
  headers: Record<string, string>;
  body?: string;
  timeoutMs: number;
};

type WindowsHttpResult = {
  status: number;
  headers?: Record<string, string>;
  bodyBase64: string;
};

export async function fetchProvider(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("user-agent", headers.get("user-agent") || "commerce-studio/0.1");
  // Some Windows network stacks reset connections when this hop-by-hop header is forced.
  headers.delete("connection");
  const requestInit = {
    ...init,
    headers,
  };
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, {
      ...requestInit,
      signal: controller.signal,
    });
  } catch (primaryError) {
    if (
      process.platform !== "win32" ||
      process.env.MODEL_WINDOWS_HTTP_FALLBACK === "false" ||
      !isSimpleRequestBody(requestInit.body)
    ) {
      throw primaryError;
    }

    try {
      return await fetchViaWindowsHttp(url, requestInit, timeoutMs);
    } catch (fallbackError) {
      const primaryCode = networkCode(primaryError) || "UNKNOWN";
      const fallbackCode = networkCode(fallbackError) || "WINDOWS_HTTP_FAILED";
      const error = new Error(
        `provider transport failed: ${primaryCode}; windows-http: ${fallbackCode}`,
      ) as Error & { cause?: unknown; code?: string };
      error.code = primaryCode;
      error.cause = fallbackError;
      throw error;
    }
  } finally {
    clearTimeout(timeout);
  }
}

export function networkCode(error: unknown) {
  if (!error || typeof error !== "object") return undefined;
  if ("code" in error && typeof error.code === "string") {
    return error.code;
  }
  if (
    "cause" in error &&
    error.cause &&
    typeof error.cause === "object" &&
    "code" in error.cause &&
    typeof error.cause.code === "string"
  ) {
    return error.cause.code;
  }
  return undefined;
}

function isSimpleRequestBody(
  body: BodyInit | null | undefined,
): body is string | null {
  return body === undefined || body === null || typeof body === "string";
}

async function fetchViaWindowsHttp(
  url: string,
  init: RequestInit & { headers: Headers },
  timeoutMs: number,
) {
  const payload: ProviderRequest = {
    url,
    method: init.method || "GET",
    headers: Object.fromEntries(init.headers.entries()),
    body: typeof init.body === "string" ? init.body : undefined,
    timeoutMs,
  };
  const encodedRequest = Buffer.from(JSON.stringify(payload), "utf8").toString(
    "base64",
  );
  const encodedScript = Buffer.from(WINDOWS_HTTP_SCRIPT, "utf16le").toString(
    "base64",
  );
  const executable =
    process.env.SystemRoot &&
    `${process.env.SystemRoot}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe`;
  const child = spawn(executable || "powershell.exe", [
    "-NoLogo",
    "-NoProfile",
    "-NonInteractive",
    "-ExecutionPolicy",
    "Bypass",
    "-EncodedCommand",
    encodedScript,
  ]);
  const stdout: Buffer[] = [];
  const stderr: Buffer[] = [];

  return await new Promise<Response>((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("windows HTTP fallback timeout"));
    }, timeoutMs + 1000);

    child.stdout.on("data", (chunk: Buffer) => stdout.push(chunk));
    child.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        const message = Buffer.concat(stderr).toString("utf8").trim();
        reject(new Error(message || `powershell exited with code ${code}`));
        return;
      }
      try {
        const result = JSON.parse(
          Buffer.concat(stdout).toString("utf8"),
        ) as WindowsHttpResult;
        const body = Buffer.from(result.bodyBase64, "base64");
        resolve(
          new Response(body, {
            status: result.status,
            headers: result.headers,
          }),
        );
      } catch (error) {
        reject(error);
      }
    });
    child.stdin.end(encodedRequest);
  });
}
