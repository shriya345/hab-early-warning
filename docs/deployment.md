# Hosted AlgaeWatch

The React frontend deploys to Vercel. The FastAPI backend and existing TensorFlow
models deploy to Railway using the root Dockerfile. Railway uses the repository
root; Vercel uses `frontend` as its project root.

## Railway backend

Deploy the repository as a Docker service. `railway.json` configures the build
and checks `/` for startup readiness. The container listens on Railway's `PORT`
and uses one worker to avoid duplicate TensorFlow model memory.

Generate a public HTTPS domain for the service. No CDSE credentials are needed
for the saved historical Vembanad prediction. Optional acquisition credentials
belong only in Railway service variables, never in frontend variables or Git.

The archived Vembanad TIFF and nine Karnataka snapshots are included in Git and
the container so the historical routes can run without this computer. Runtime
caches are ephemeral. A successful `/` response confirms the API started; it
does not verify model inference or external source availability.

## Vercel frontend

Import the same repository with its root directory set to `frontend`.
`frontend/vercel.json` installs and builds the frontend and serves `dist`.
Set `VITE_API_BASE_URL` to the Railway HTTPS origin (without `/api`). It is public
configuration, not a secret. Redeploy after changing it because Vite embeds it
at build time. Local development defaults to the existing `/api` proxy.

## Post-deployment checks

- Open the frontend and search the Karnataka catalogue.
- Load a saved historical snapshot for a supported archived water body.
- POST `/historical-predictions/vembanad` on the backend and confirm the existing
  CNN and LSTM produce the archived result, with its original dates and caveats.
- Confirm unvalidated Karnataka live predictions remain unavailable.

Railway resource usage and availability depend on the account plan. Historical
model execution needs enough memory for TensorFlow and the archived raster.
