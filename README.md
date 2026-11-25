This is a RESTful event ticketing backend built with Flask, PostgreSQL, and a two-service architecture. Event Ticketing System allows organizers to manage events and ticket inventory while users discover events, reserve tickets, and receive individually issued tickets after organizer approval.
This project doesn't only implement CRUD, but also secure authentication, resource-level authorization, transactional inventory management, concurrent purchase handling, idempotency, and automatic order expiration.
## Live Demo and API Access
Web application: https://event-ticketing-system-bia5.vercel.app/ \
Auth Service: https://event-ticketing-system-pearl.vercel.app/ \
Ticketing Service: https://event-ticketing-system-qi1m.vercel.app/ \
Postman API documentation: https://documenter.getpostman.com/view/59293580/2sBYPv3sh2 

The frontend is provided as a demonstration client. Both backend services can be accessed directly using Postman or another HTTP client.

## Table of Contents
- [Background](#background)
- [Core Features](#core-features)
- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Database Design](#database-design)
- [Business Logic and Order Lifecycle](#business-logic-and-order-lifecycle)
- [API Reference](#api-reference)
- [Security](#security)
- [Concurrency and Data Integrity](#concurrency-and-data-integrity)
- [Local Installation](#local-installation)
- [Limitations](#limitations)
- [Acknowledgments](#acknowledgements)

## Background
Event organizers need a reliable way to publish events, manage ticket availability, validate orders, and verify attendance. A ticketing backend must be able to handle situations where multiple users attempt to reserve the same remaining tickets, clients retry requests, or pending reservations are abandoned.
This system addresses these problems by separating authentication from ticketing operations and enforcing inventory and order rules at both the application and database levels. The initial scope uses manual organizer approval rather than an integrated payment gateway.

## Core Features
#### Attendees (user)
- Register, log in, retrieve account information, and request password recovery.
- Browse published or canceled events, search by title, and filter by category, location, or date.
- View available ticket types and remaining inventory.
- Create orders with a maximum of five pending and confirmed tickets per event.
- Track order status and cancel eligible pending orders.
- Access individually issued tickets after approval, including private online event information when applicable.
#### Organizers (organizer)
- Create draft events, configure ticket types, and publish events.
- Manage owned events and update ticket capacity within inventory constraints.
- View, approve, or reject orders associated with owned events.
- Cancel events or delete eligible unused drafts.
- Verify issued ticket codes and perform check-in during the event's allowed time window.
#### Backend Features
- Independent Auth and Ticketing services with asymmetric RS256 JWT authentication.
- PostgreSQL transactions, row-level locking, unique constrains, and inventory consistency checks.
- Idempotent order creation using UUID v4 request keys and SHA-256 payload fingerprints.
- Automatic order expiration and reserved stock recovery through lazy expiration and Vercel Cron.
- Role-based and object-level authentication, input validation, rate limiting, and audit logs.
- Schema versioning with Flask-Migrate/Alembic.

## System Architecture
<img width="1112" height="512" alt="event_ticketing" src="https://github.com/user-attachments/assets/99b0b02a-1223-447a-9ed4-d479e5572ad8" /> \
#### Description: 
Auth Service:	Accounts, password hashing, login, JWT issuance, password reset, authentication rate limits \
Ticketing: Service	Events, ticket inventory, orders, ticket issuance, check-in, expiration, audit records\
Frontend: Demonstration interface and HTTP proxy to the backend services\
PostgreSQL/Neon:	Persistent relational data owned by each backend service\
Vercel Cron:	Periodic authenticated requests to process overdue orders\
SMTP:	Delivery of password reset links

The Auth Service signs access tokens with its RSA private key. The Ticketing Service verifies those tokens using the corresponding public key, issuer, audience, and expiration claims. Ticketing does not need the private signing key or direct access to the Auth database. \
User and organizer IDs are carried across service boundaries as logical references. They are not cross-database foreign keys. Both services can be deployed independently, but this design requires compatible token configuration and careful coordination of changes to shared identity claims.

## Technology Stack
Python 3.13:	Backend development and local testing\
Flask:	HTTP routing and application factories\
Flask-SQLAlchemy/SQLAlchemy:	ORM, parameterized queries, transactions, row locks\
PostgreSQL/Neon:	Relational storage and concurrency control\
psycopg:	PostgreSQL database driver\
Flask-Migrate/Alembic:	Database schema migrations\
Flask-JWT-Extended/cryptography:	RS256 JWT signing and verification\
Werkzeug:	Salted password hashing and verification\
Flask-Limiter:	Ticketing endpoint rate limits\
python-dotenv:	Local environment configuration\
email-validator/smtplib:	Email validation and password reset delivery\
Postman:	Manual API testing and documentation\
Vercel/Vercel Cron:	Service deployment and scheduled processing\
HTML, CSS, JavaScript, Flask-requests:	Demonstration frontend and API proxy\

## Project Structure
```
EventFlow/
├── auth/
│   ├── app.py
│   ├── factory.py
│   ├── config.py
│   ├── extensions.py
│   ├── models.py
│   ├── routes.py
│   ├── security.py
│   ├── mailer.py
│   ├── migrations/
│   └── requirements.txt
├── ticketing/
│   ├── app.py
│   ├── factory.py
│   ├── config.py
│   ├── extensions.py
│   ├── models.py
│   ├── event_routes.py
│   ├── ticket_routes.py
│   ├── order_routes.py
│   ├── cron_routes.py
│   ├── expiration.py
│   ├── helpers.py
│   ├── rate_limit.py
│   ├── audit.py
│   ├── migrations/
│   ├── requirements.txt
│   └── vercel.json
├── frontend/
│   ├── app.py
│   └── templates/
├── .gitignore
└── README.md
```
Application factories initialize extensions and register route modules. Models describe persistence and database constraints; route modules coordinate business rules; shared helper modules handle validation, authorization, and serialization. Expiration and audit functions are separated to reduce duplication.

## Database Design
#### Auth Database
`users` : Account identity, unique email and username, password hash, role
`password_reset_tokens` : Hashed recovery tokens, expiry, and usage timestamps
`rate_bucket` : Persistent authentication request counters scoped by hashed identifiers
<img width="6176" height="3192" alt="auth_database" src="https://github.com/user-attachments/assets/f38e456f-24c2-4997-b863-4336575c2477" />

#### Ticketing Database
`events`:	Event metadata, organizer ID, schedule, status and location or meeting URL\
`ticket_types`:	Ticket categories, price, capacity, reserved and sold stock, sale period\
`orders`:	User reservations, quantity, total price, status, expiration and validation information\
`issued_tickets`:	Individual ticket codes, validity, issue and check-in timestamps\
`idempotency_records`:	Request keys, fingerprints and saved responses\
`audit_logs`:	Selected operations, acting user ID, target ID and timestamp\
<img width="6176" height="3192" alt="ticketing_database" src="https://github.com/user-attachments/assets/137074b4-434f-4587-8b05-c4fe6aa6a596" />
The diagrams show key attributes and physical foreign-key relationships; the model files define the complete schema. idempotency_records and audit_logs use logical identifiers, not foreign keys to another service. Important database protections include:
- Unique usernames, emails, ticket codes, and ticket type names within an event.
- Composite uniqueness for idempotency keys scoped to a user and operation.
- A partial unique index allowing only one pending order per user per event.
- Check constraints on statuses, date ranges, quantities, prices, and stock capacity.
- A partial index on (expires_at, event_id) for pending-order expiration queries.

## Business Logic and Order Lifecycle
#### Event Lifecycle
<img width="344" height="401" alt="event_lifecycle drawio" src="https://github.com/user-attachments/assets/43e3645d-2002-45c2-8ba5-b602b745e3bd" /> \
Events always start as drafts. Publication requires an appropriate future schedule and at least one ticket type. Once an order exists, updates to event information are restricted to its description. Canceling an event cancels remaining pending orders, releases reservations, and invalidates issued tickets; it does not process financial refunds.
#### Order Lifecycle
<img width="581" height="325" alt="event_lifecycle drawio (1)" src="https://github.com/user-attachments/assets/ee534f2d-4602-4b3d-bda9-11203225c132" /> \
Flow:
1. A user submits a ticket type, quantity, valid access token, and unique idempotency key.
2. The backend verifies the event status, sale period, available stock, and purchase limits.
3. Stock is reserved and the order is created as pending within one database transaction.
4. Organizer approval moves the reserved quantity to sold stock and issues one ticket per purchased unit.
5. Rejection, cancellation, or expiration releases reserved stock without deleting the order history.
6. An authorized organizer can check in a valid issued ticket during the event time window. Successful check-in marks the ticket as used.

## Inventory Management
Formula: `available_stock = total_stock - reserved_stock - sold_stock`
|Operation|Total|Reserved|Sold|Available|
|---|---|---|---|---|
|Base|10|0|0|10|
|Order created|10|3|0|7|
|If order is approved|10|0|3|7|
|If order is expired instead|10|0|0|10|

Approval and expiration are alternative outcomes for the same pending order. The database enforces nonnegative stock counters and the `reserved_stock+sold_stock<=total_stock` rule.

#### Automatic Order Expiration
The default reservation duration is 30 minutes and is changeable through ORDER_EXPIRATION_MINUTES constant variable. An order is not eligible for approval beyond the event start time. \
Expiration is processed in two ways:
- Lazy expiration: relevant order and ticket operations check overdue pending orders and release stock within database transactions.
- Scheduled expiration: Vercel Cron invokes `GET /internal/expire-orders` once a day using a dedicated bearer secret. The configured schedule is 07.00 WIB.
The deadline and cron frequency are different concepts. A 30-minute deadline does not mean the cron job runs every 30 minutes. An overdue order may remain recorded as pending until a relevant request or scheduled cleanup processes it. Expiration updates the status rather than deleting the order, and repeated processing does not release the same reservation twice.

## API Reference
Base URLs: 
```
Auth:      https://event-ticketing-system-pearl.vercel.app
Ticketing: https://event-ticketing-system-qi1m.vercel.app
```

## Security
- Password storage: Werkzeug generates salted password hashes. Plaintext passwords are not stored.
- Authentication: RS256-signed JWT access tokens, with a default 15-minutes validity.
- Token validation: Implemented signature, issuer, audience, and expiration verification.
- Role based access control: Implemented aeparate user and organizer privileges.
- Object-level authorization: Implemented ownership checks on event, order, and issued ticket operations
- Anti SQL injection: Implemented SQLAlchemy expressions and parameterized queries, which escaped search wildcards.
- Input validation: Done JSON structure, numeric limits, email and username uniqueness validation, date validation, URL validation, and allowed fields.
- Password recovery: Generate random reset tokens, send to your registered email with SHA-256 token hashes, 30 minutes expiry, single-use enforcement, and transactional updates.
- Rate limiting: Used Postgresql-backed authentication counters and flask limiter for selected ticketing routes.
- Internal authorization: Used dedicated cron secret checked using constant-time comparison.
- Confidential event data: Meeting URLs are restricted to authorized access paths.
- Audit logging: Selected state-changing operations record actor, action, target, and time.
- Error handling: Implemented transaction rollback and generic unexpected error responses, with detailed server-side logging.

## Concurrency and Data Integrity
### 1. Pessimistic Locking
Ticketing operations use PostgreSQL row-level locks on the relevant event, ticket type, and order rows. A consistent lock order helps avoid conflicting updates. A transaction holding the required lock can validate and update inventory before another conflicting transaction proceeds. For example, when two users attempt to purchase the final available ticket, the concurrency system will generate one successful (201 Created) and one failed (409 Conflict). Only one reservation is stored.
### 2. Transaction Atomicity
Order creation, stock changes, idempotency response persistence and relevant audit records are committed as a unit. Organizer approval atomically updates the order, moves reserved stock into sold stock and creates the issued tickets. If a transaction fails, its uncommited changes are rolled back.
### 3. Idempotency
POST /orders requires an Idempotency-Key which contains a UUID v4. A Postgresql unique constraint and atomic insert-on-conflict operation coordinate concurrent requests using the same key. A SHA-256 fingerprint of the normalized payload prevents accidental reuse with a different request body. Multiple scenarios:
- Same user, operation, key and payload: replay the original saved response without creating a second order.
- Same user, operation, and key with a different payload: return a 409 conflict.
- A new logical purchase after rejection, cancellation, or expiration: use a new key.

## Local Installation
#### Prerequisites
- Python 3.13 and pip.
- Git
- Two postgresql databases, plus an isolated postgresql test database.
- An RSA key pair for JWT signing and verification.
- SMTP credentials if testing real password recovery email.
Clone this repository, then open the repository root in a terminal.
##### 1. Generate a development RSA key pair.
If OpenSSL is available, generate a dedicated local key pair outside the repository.\
```
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out jwt_private.pem
openssl pkey -in jwt_private.pem -pubout -out jwt_public.pem
```
Keep the private key private. The Auth Service needs both keys, while Ticketing only needs the public key. Do not reuse production signing keys for development.
##### 2. Configure auth service
In your terminal:
```
cd auth
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Then, create auth/.env using your own values:
```
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/AUTH_DB?sslmode=require
JWT_PRIVATE_KEY_PATH=C:/path/to/jwt_private.pem
JWT_PUBLIC_KEY_PATH=C:/path/to/jwt_public.pem
APP_ENV=development
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
SMTP_USE_SSL=false
MAIL_FROM=sender@example.com
RESET_PAGE_URL=http://localhost:8000/reset-password
```
Alternatively, provide the PEM contents through JWT_PRIVATE_KEY and JWT_PUBLIC_KEY. SMTP settings are provider-specific. The values above are placeholders.\
Apply the existing database migrations and start the Auth Service:
```
.\.venv\Scripts\python.exe -m flask --app app db upgrade
.\.venv\Scripts\python.exe -m flask --app app run --port 8001
```
##### 3. Configure Ticketing Service
Open another terminal at the repository root:
```
cd ticketing
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Create ticketing\.env:
```
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/TICKETING_DB?sslmode=require
JWT_PUBLIC_KEY_PATH=C:/path/to/jwt_public.pem
ORDER_EXPIRATION_MINUTES=30
CRON_SECRET=replace_with_a_random_secret
RATELIMIT_STORAGE_URI=memory://
```
Generate a unique local cron secret with Python if needed:
`.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"`
Apply migrations and start the Ticketing Service:
```
.\.venv\Scripts\python.exe -m flask --app app db upgrade
.\.venv\Scripts\python.exe -m flask --app app run --port 8002
```
Run database migrations against the intended service database, preferably using a direct PostgreSQL connection for administrative operations. Do not initialize a new migration history when the repository already contains one.\

##### 4. Run the Frontend (Opsional)
The deployed frontend uses production service URLs. To test a;; three services locally, configure frontend's AUTH_URL and TICKETING_URL to http://localhost:8001 and http://localhost:8002 respectively, instead of production URLs.
```
cd frontend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install Flask requests
.\.venv\Scripts\python.exe -m flask --app app run --port 8000
```
Open http://localhost:8000 in a browser, or test the two backend services independently through Postman.

##### 5. Postman Testing
Use a private Postman environment with variables such as:
```
auth_url
ticketing_url
user_token
organizer_token
event_id
ticket_type_id
order_id
idempotency_key
cron_secret
```
Keep real access tokens, reset tokens, credentials, and cron secrets out of published collections, examples, screenshoots, and shared variables values.
A recommended testing flow:
1. Register and log in as an organizer and a separate user.
2. Create a future event, add a ticket type with an active sale period, and publish the event.
3. Create an order using the user token and a fresh UUID v4; verify reservation and expiration fields.
4. Retry with the same key and payload; verify that no extra order or reservation is created.
5. Approve using the event owner's organizer token; verify sold stock and issued tickets.
6. Test a separate expired order and confirm reserved stock is returned without issuance.
7. Check unauthorized access, malformed requests, insufficient stock, invalid order transitions, and rejected cron credentials.
8. Perform check-in during a valid event time window and confirm a used ticket cannot be checked in again.

## Limitations
Event Ticketing System is an academic backend project, not a fully commercial ticketing platform. Hence, there are multiple limitations:
- Manual approval: payment processing, settlement, refunds, and payment reconciliation are not integrated.
- JWT revocation: logout discards the client token but does not immediately revoke it on the server. Existing tokens may remain valid after password changes until expiration.
- Expiration timing: lazy expiration and a daily cron provide recover rather than guaranteed real-time background process.
- Distributed rate limiting: Ticketing uses in-memory rate limiting by default, which is not shared accross all serverless instances. A shared backend would improve consistency.
- Operational scope: audit coverage is selective; monitoring, alerting, data retention, organizer verification, and disaster recover would require further work for commercial deployment.

## Future Improvements
- Payment-provider integration
- Refresh-token rotation and revocation
- Shared rate-limit storage
- More frequent expiration workers
- Load testing
- Organizer verification

## Acknowledgements
Event Ticketing System is developed as a backend development assignment for OmahTI 2026. Open-source libraries and hosted services are listed in the technology stack. AI assistance was used during development for frontend development, logic review, advisor, and technical explanations of concepts I'm not familiar to.
