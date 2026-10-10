// Empty = same origin (local uvicorn / Railway serving UI).
// On Vercel: set project env AAS_API_BASE to the Railway HTTPS URL;
// `npm run build` runs inject-api-base.js and overwrites this file.
window.AAS_API_BASE = "";
