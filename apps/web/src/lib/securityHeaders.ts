/**
 * Response headers for every page and route of the web app (P8-M1, ADR-035).
 *
 * The Content Security Policy is the documented Next.js variant without nonces:
 * scripts and styles only from this origin, plus inline ones that Next.js needs
 * for hydration ('unsafe-inline'; nonces would force every page to render
 * dynamically). It still blocks scripts and frames from other origins, plugins,
 * form posts and requests to other origins, and being framed. React escapes
 * all text the app shows and no component injects HTML, which is what keeps
 * inline script injection out.
 */

export interface SecurityHeader {
  key: string;
  value: string;
}

export function contentSecurityPolicy(environment: string | undefined): string {
  const development = environment === "development";
  // No upgrade-insecure-requests: every resource is same-origin already, and
  // `next start` runs in production mode on plain http://localhost too, where
  // upgrading same-origin requests to https would break the app.
  return [
    "default-src 'self'",
    // React needs eval only in development (debugging information).
    `script-src 'self' 'unsafe-inline'${development ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}

export function securityHeaders(environment: string | undefined): SecurityHeader[] {
  const headers: SecurityHeader[] = [
    { key: "Content-Security-Policy", value: contentSecurityPolicy(environment) },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "X-Frame-Options", value: "DENY" },
    {
      key: "Permissions-Policy",
      value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    },
  ];
  // Browsers ignore HSTS received over plain http (RFC 6797), so it is harmless
  // for `next start` on http://localhost and takes effect once served over https.
  if (environment === "production") {
    headers.push({
      key: "Strict-Transport-Security",
      value: "max-age=31536000; includeSubDomains",
    });
  }
  return headers;
}
