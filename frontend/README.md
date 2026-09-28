# Aranya frontend

React, TypeScript, and Vite interface for the existing Aranya API. This folder can be built and deployed independently; it does not change or bundle backend behavior.

## Development

```sh
npm install
cp .env.example .env.local
npm run dev
```

The app defaults to `http://localhost:8000` as its API origin. Set `VITE_API_BASE_URL` to another origin before building, or change the origin on the sign-in screen. The backend must permit the frontend origin through its existing CORS configuration.

## Production build

```sh
npm run build
npm run preview
```

Deploy the contents of `dist/` to a static host that supports SPA fallback to `index.html`. Configure `VITE_API_BASE_URL` at build time. The frontend contains no API secrets. The sign-in screen saves a user-provided API origin in browser storage; the selected farm ID and bearer session are also stored locally, matching the prior frontend’s behavior.

## Existing API flows

OTP sign-in; crop and livestock scans; weather and soil analysis; planting planning; market checks; field history; economics expense/sale/crop-cycle operations; scheme matching; research; text and voice chat; alerts and acknowledgement; consultation listing and expert-only resolution; and recommendation outcome feedback.

The backend does not expose farm creation or selection in the current contract. Farmers enter an existing farm ID in the persistent shell context. No client-side agricultural data or sample response is synthesized.
