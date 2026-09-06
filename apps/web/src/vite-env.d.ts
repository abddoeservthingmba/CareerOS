/// <reference types="vite/client" />

/**
 * The one variable the client reads from its environment.
 *
 * Declared rather than inferred so a typo in `import.meta.env.VITE_API_BSAE_URL`
 * is a type error instead of `undefined` at runtime - which on a health strip
 * reads as "the API is down" rather than "nobody configured this".
 */
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
