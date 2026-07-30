# System architecture

Diagram: where leads come from, who processes them, and where data goes.

```mermaid
graph TD
    subgraph Lead_sources["Lead sources"]
        SITE["Website / lead form"]
        TG_CLIENT["Telegram customer"]
    end

    subgraph CRM_users["CRM users"]
        HEAD["Head<br/>spam and lead review"]
        MANAGER["Manager<br/>deals and clients"]
    end

    subgraph Processes["Django processes"]
        WEB["Web server<br/>CRM UI + API"]
        WORKER["Inbound worker<br/>antispam + AI + deal creation"]
        BOT["Telegram chat-bot<br/>customer messages"]
    end

    subgraph Storage["Database"]
        DB[("SQLite<br/>leads, clients, deals")]
    end

    subgraph External_services["External services"]
        AI["AI: Ollama or OpenAI<br/>lead text analysis"]
        TG_API["Telegram API<br/>outbound replies"]
    end

    SITE -->|"Signed request<br/>new lead"| WEB
    WEB -->|"Store request<br/>status: received"| DB

    WORKER -->|"Pick up new requests"| DB
    WORKER -->|"Antispam rules<br/>+ AI analysis"| AI
    WORKER -->|"Create client and deal<br/>or mark as spam"| DB

    TG_CLIENT -->|"Message"| BOT
    BOT -->|"Create / append request"| DB
    BOT <-->|"Verify and send messages"| TG_API

    HEAD -->|"Requests screen<br/>moderation"| WEB
    MANAGER -->|"Deals screen"| WEB
    WEB <-->|"Read and write"| DB
```

## How to read the diagram

1. **Website or Telegram** sends an inquiry.
2. The **web server** accepts the lead and stores it in the database.
3. The **worker** checks for spam, may call **AI**, then creates a deal or blocks the request.
4. The **head** reviews suspicious requests in Admin Ops.
5. The **manager** works with normal deals in CRM.

## Processes

| Command | Required | Purpose |
|---------|----------|---------|
| `python manage.py runserver` | yes | CRM UI and intake API |
| `python manage.py process_inbound` | yes | Worker: antispam, AI, deal creation |
| `python manage.py run_admin_bot` | no | Telegram chat-bot for customers |
