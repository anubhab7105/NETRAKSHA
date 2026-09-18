```mermaid
graph TD
    Client[Client App] --> API[FastAPI Backend]
    API <--> DB[(Supabase PostgreSQL)]
    API --> Pipeline{Analysis Pipeline}
```
