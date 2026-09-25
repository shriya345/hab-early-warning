// Public backend URL only. Credentials belong in the backend environment.
export const API = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
