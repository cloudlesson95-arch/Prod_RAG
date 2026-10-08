# Web frontend

Next.js app over the RAG API: chat, demo sandbox and dashboard. Setup, deploy and checks are in the repository README.

```powershell
npm ci
Copy-Item .env.example .env.local   # then set the backend URL(s)
npm run dev                          # http://localhost:3000
```

Checks: `npm run lint`, `npm test`, `npm run build`.
