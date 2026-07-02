# Codex Instructions — Local Restaurant Order & Kitchen Printing App

## Project goal

Build a local-first restaurant order management application for a small food/bar/asporto workflow.

The application must be simple, reliable, self-hosted, and designed to run on a local PC used as the cashier station. Other devices on the same LAN, such as tablets or smartphones, should be able to access the app through a browser.

This is not intended to be a full restaurant ERP, accounting system, inventory system, fiscal cash register, or invoicing platform. The goal is to manage orders and print the right tickets to the right printers.

## Core use case

The main workflow is:

1. The cashier takes an order from the main PC.
2. The system assigns a progressive daily order number.
3. The system prints a customer receipt/ticket with the full order and a large order number.
4. The system prints production tickets to different printers depending on item category.
   - Example: food items go to the kitchen printer.
   - Example: drinks go to the bar printer.
5. The customer pays at the cashier station.
6. The customer collects the order when the number is called.

The system should also support the possibility of taking orders from a smartphone or tablet on the same LAN, ideally using the same web interface or a simplified responsive interface.

## Technical direction

Prefer a local web application over a traditional desktop application.

Recommended stack:

- Python 3.12+
- FastAPI
- SQLite
- SQLAlchemy
- Jinja2 templates
- HTMX
- Bootstrap or another simple CSS framework
- Uvicorn
- python-escpos or equivalent ESC/POS printing library

Keep the project simple and maintainable.

Avoid heavy frontend frameworks unless strictly necessary. Do not use cloud services. Do not require external paid APIs.

## Deployment model

The app should run on a local PC or mini PC inside the restaurant.

Example:

```text
Cashier PC:
  http://localhost:8000

Smartphone/tablet on same LAN:
  http://192.168.1.10:8000
```

The app must bind optionally to `0.0.0.0` so that other devices on the LAN can connect.

The initial target OS is Windows, but the code should be portable enough to run on Linux if possible.

## Out of scope

Do not implement:

- fiscal receipts
- Italian telematic cash register integration
- electronic invoicing
- full inventory management
- warehouse management
- staff payroll
- delivery marketplace integrations
- online ordering from the public Internet
- payment gateway integration
- cloud sync
- multi-restaurant chain management

The app may print non-fiscal customer order tickets and kitchen/bar production tickets.

Fiscal handling will be done separately through a fiscal register or another system.

## Main entities

### Product

Each product must have:

- id
- name
- price in cents
- category
- active/inactive flag
- sort order
- optional description
- optional notes/modifiers support in the future

Important: when an order is created, copy the product name, category name, unit price, and assigned printer into the order item. Do not rely on live product data for old orders.

### Category

Each category must have:

- id
- name
- optional assigned printer
- sort order
- active/inactive flag

Example categories:

- Cucina
- Bar
- Bevande
- Dolci
- Menu

A category should be assignable to a production printer. Items in that category should be printed to that printer when the order is confirmed.

### Printer

Each printer must have:

- id
- name
- type
- IP address
- port
- enabled/disabled flag
- optional fallback/test mode

Printer types:

- network ESC/POS printer
- fake/test printer writing to text files
- optionally Windows printer in a later version

Initial implementation should focus on network ESC/POS printers on port 9100.

Example:

```text
Customer printer:
  ip: 192.168.1.50
  port: 9100

Kitchen printer:
  ip: 192.168.1.51
  port: 9100

Bar printer:
  ip: 192.168.1.52
  port: 9100
```

### Order

Each order must have:

- id
- order number
- business date
- status
- total in cents
- source
- created_at
- paid_at
- completed_at
- optional notes

Suggested statuses:

- draft
- pending_confirmation
- confirmed
- paid
- ready
- delivered
- cancelled

For the MVP, these are enough:

- confirmed
- paid
- delivered
- cancelled

The system must support progressive daily order numbers.

Example:

```text
2026-07-02 order 001
2026-07-02 order 002
2026-07-03 order 001
```

Add a unique database constraint on:

```sql
business_date, order_number
```

### Order item

Each order item must have:

- id
- order_id
- product_id, nullable
- product_name copied at sale time
- category_name copied at sale time
- printer_id copied at sale time
- quantity
- unit_price_cents copied at sale time
- line_total_cents
- notes

## Database schema draft

Use SQLAlchemy models and migrations if convenient. Alembic is optional for the MVP.

Suggested schema:

```sql
printers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  ip TEXT,
  port INTEGER DEFAULT 9100,
  enabled BOOLEAN DEFAULT 1,
  is_customer_printer BOOLEAN DEFAULT 0
);

categories (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  printer_id INTEGER,
  active BOOLEAN DEFAULT 1,
  sort_order INTEGER DEFAULT 0,
  FOREIGN KEY(printer_id) REFERENCES printers(id)
);

products (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  price_cents INTEGER NOT NULL,
  category_id INTEGER NOT NULL,
  active BOOLEAN DEFAULT 1,
  sort_order INTEGER DEFAULT 0,
  FOREIGN KEY(category_id) REFERENCES categories(id)
);

orders (
  id INTEGER PRIMARY KEY,
  order_number INTEGER NOT NULL,
  business_date TEXT NOT NULL,
  status TEXT NOT NULL,
  total_cents INTEGER NOT NULL,
  source TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL,
  paid_at TEXT,
  completed_at TEXT,
  UNIQUE(business_date, order_number)
);

order_items (
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL,
  product_id INTEGER,
  product_name TEXT NOT NULL,
  category_name TEXT NOT NULL,
  printer_id INTEGER,
  quantity INTEGER NOT NULL,
  unit_price_cents INTEGER NOT NULL,
  line_total_cents INTEGER NOT NULL,
  notes TEXT,
  FOREIGN KEY(order_id) REFERENCES orders(id),
  FOREIGN KEY(product_id) REFERENCES products(id),
  FOREIGN KEY(printer_id) REFERENCES printers(id)
);

users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  pin_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  active BOOLEAN DEFAULT 1
);

print_jobs (
  id INTEGER PRIMARY KEY,
  order_id INTEGER NOT NULL,
  printer_id INTEGER,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_text TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL,
  printed_at TEXT,
  FOREIGN KEY(order_id) REFERENCES orders(id),
  FOREIGN KEY(printer_id) REFERENCES printers(id)
);
```

## Pages and UI

### 1. Cashier screen

This is the main page.

Requirements:

- product buttons grouped by category
- large touch-friendly buttons
- cart on the side
- quantity controls
- remove item
- add note to item
- order total
- confirm and print button
- cancel current cart button
- optional mark as paid button

Suggested layout:

```text
+-----------------------------------------------------+
| Categories: [Tutti] [Cucina] [Bar] [Bevande]        |
+-------------------------------+---------------------+
| Product buttons               | Current cart        |
| [Panino] [Patatine] [Birra]   | 2x Panino  12.00    |
| [Caffe]  [Acqua]    [Menu]    | 1x Birra    5.00    |
|                               | Total:     17.00    |
|                               | [Confirm & Print]   |
+-------------------------------+---------------------+
```

### 2. Products admin

Admin page for:

- create product
- edit product
- disable product
- assign category
- set price
- set sort order

### 3. Categories admin

Admin page for:

- create category
- edit category
- disable category
- assign printer
- set sort order

### 4. Printers admin

Admin page for:

- create printer
- edit printer
- test printer
- set IP and port
- set as customer printer
- enable fake printer mode

### 5. Orders history

Page for:

- list orders by date
- view order details
- reprint customer ticket
- reprint production tickets
- mark as delivered
- cancel order if needed

### 6. Mobile order page

Responsive page for smartphones/tablets.

MVP behavior:

- allow staff to create an order from a mobile device
- save it as `pending_confirmation`
- cashier must confirm and print it

Later behavior:

- authorized users may confirm and print directly from mobile

## Printing requirements

Printing reliability is critical.

Implement a print service with these capabilities:

1. Generate plain text ticket content first.
2. Save the content as a print job in the database.
3. Attempt to print.
4. Mark the print job as printed or failed.
5. Allow manual reprint from order history.

Do not generate an order and print without storing what was printed.

### Customer ticket

The customer ticket contains the full order.

Example:

```text
==============================
        ORDINE N. 124
==============================

2 x Panino salamella       12.00
1 x Birra media             5.00
1 x Patatine                3.50

------------------------------
TOTALE                     20.50

Ritira quando viene chiamato:
        124

Grazie!
```

The order number must be visually large. In ESC/POS, use double width/double height or similar formatting.

### Kitchen ticket

Contains only items assigned to the kitchen printer.

Example:

```text
====== CUCINA ======
ORDINE N. 124
Ora: 19:42

2 x Panino salamella
1 x Patatine

Note:
- Panino senza cipolla
```

### Bar ticket

Contains only items assigned to the bar printer.

Example:

```text
====== BAR ======
ORDINE N. 124
Ora: 19:42

1 x Birra media
1 x Caffe
```

### Grouping logic

When an order is confirmed:

1. Generate one customer ticket with all items.
2. Group order items by `printer_id`.
3. For each printer group, generate one production ticket.
4. If an item has no assigned printer, either:
   - skip production printing and show warning, or
   - print it on a default production printer if configured.

For MVP, show a clear warning if a product category has no production printer.

### Fake printer mode

Implement a fake printer type that writes print jobs to files.

Example:

```text
print_output/
  2026-07-02_order_124_customer.txt
  2026-07-02_order_124_kitchen.txt
  2026-07-02_order_124_bar.txt
```

This is mandatory for testing without real printers.

## Order number generation

Order number generation must be transactional and safe.

When confirming an order:

1. Start a database transaction.
2. Determine current business date.
3. Read the max order number for that business date.
4. Assign max + 1.
5. Save order and items.
6. Commit.
7. Then process print jobs.

Avoid assigning duplicate order numbers when multiple devices confirm at the same time.

For SQLite, use careful transaction handling. If concurrency becomes a problem, document that PostgreSQL is recommended for multi-device heavy usage.

## Authentication and roles

Implement basic PIN login.

Roles:

- admin
- cashier
- waiter
- kitchen

Permissions:

- admin:
  - manage products
  - manage categories
  - manage printers
  - view history
  - reprint
- cashier:
  - create orders
  - confirm orders
  - print
  - reprint
  - mark delivered
- waiter:
  - create mobile orders
  - submit pending orders
- kitchen:
  - view order status only, future feature

For MVP, implement admin and cashier. Add waiter if mobile ordering is implemented early.

Do not store PINs in plain text. Store a hash.

## API endpoints

Suggested endpoints:

```text
GET  /                       cashier screen
GET  /login
POST /login
POST /logout

GET  /products
POST /products
GET  /products/{id}/edit
POST /products/{id}/edit
POST /products/{id}/disable

GET  /categories
POST /categories
GET  /categories/{id}/edit
POST /categories/{id}/edit

GET  /printers
POST /printers
GET  /printers/{id}/edit
POST /printers/{id}/edit
POST /printers/{id}/test

POST /orders
GET  /orders
GET  /orders/{id}
POST /orders/{id}/reprint/customer
POST /orders/{id}/reprint/production
POST /orders/{id}/mark-paid
POST /orders/{id}/mark-delivered
POST /orders/{id}/cancel

GET  /mobile
POST /mobile/orders
```

If using HTMX, keep responses simple partial HTML snippets where useful.

## Initial seed data

Provide a seed command or automatic first-run setup.

Seed example:

Categories:

- Cucina
- Bar
- Bevande

Printers:

- Customer Printer, fake mode
- Kitchen Printer, fake mode
- Bar Printer, fake mode

Products:

- Panino salamella, 600 cents, Cucina
- Patatine, 350 cents, Cucina
- Birra media, 500 cents, Bar
- Caffe, 120 cents, Bar
- Acqua, 100 cents, Bevande

Users:

- admin with PIN 1234
- cashier with PIN 1111

Make it clear in the README that default PINs must be changed.

## Error handling

The system must handle:

- printer offline
- printer IP not reachable
- product without category
- category without printer
- empty cart
- invalid quantity
- duplicate order number attempt
- database write failure

If printing fails:

- the order must remain saved
- print job must be marked failed
- user must see a clear warning
- user must be able to retry printing

## Data safety

Implement:

- SQLite database file in a configurable data directory
- automatic daily backup of the SQLite file, if simple to add
- export orders to CSV, optional
- no cloud dependency

Do not delete old orders by default.

## Configuration

Use environment variables or a `.env` file.

Suggested settings:

```text
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=sqlite:///./data/app.db
BUSINESS_DAY_RESET_HOUR=4
PRINT_OUTPUT_DIR=./print_output
SECRET_KEY=change-me
```

Business date should normally change at a configurable reset hour, not necessarily midnight. For example, if the restaurant closes after midnight, orders before 04:00 can still belong to the previous business day.

## README requirements

Generate a clear README with:

- project purpose
- features
- out-of-scope items
- installation
- running locally
- accessing from another LAN device
- database initialization
- default users/PINs
- fake printer testing
- ESC/POS printer configuration
- troubleshooting printing
- backup notes

## Testing requirements

Add basic tests for:

- product creation
- category creation
- order creation
- daily order number increment
- unique order number per business date
- grouping items by printer
- fake printer output generation
- failed printer job handling if easy to simulate

Use pytest.

## Suggested folder structure

```text
restaurant_pos/
  app/
    main.py
    config.py
    database.py
    models.py
    schemas.py
    auth.py
    services/
      orders.py
      printing.py
      numbering.py
    routers/
      cashier.py
      products.py
      categories.py
      printers.py
      orders.py
      mobile.py
    templates/
      base.html
      login.html
      cashier.html
      products.html
      categories.html
      printers.html
      orders.html
      order_detail.html
      mobile.html
    static/
      css/
      js/
  tests/
  data/
  print_output/
  requirements.txt
  README.md
  .env.example
```

## Implementation priority

Build in this order:

1. Project skeleton and README.
2. Database models.
3. Seed data.
4. Product/category/printer admin pages.
5. Cashier screen.
6. Order creation with progressive daily number.
7. Fake printer output.
8. ESC/POS network printer support.
9. Orders history and reprint.
10. PIN login.
11. Mobile responsive order page.
12. Optional kitchen/bar status dashboard.

## Design principles

- Prefer reliability over aesthetics.
- Prefer simple server-rendered pages over complex frontend architecture.
- Make all print operations auditable.
- Never lose an order because a printer is offline.
- Keep fiscal functionality out of scope.
- Keep the app usable without Internet.
- Keep configuration understandable by a technical owner.
- Avoid vendor lock-in.
- Make the database easy to back up.
- Make the UI fast and touch-friendly.

## Final expected result

The first working version should allow a user to:

1. Start the server.
2. Log in as cashier.
3. Add/edit products, categories, and printers.
4. Create an order from the cashier screen.
5. Confirm the order.
6. Get a progressive daily order number.
7. Generate a customer ticket.
8. Generate separate kitchen/bar tickets based on product category.
9. View the order in history.
10. Reprint tickets if needed.
11. Access the cashier/mobile page from a phone on the same LAN.

The application should be small, local-first, self-hosted, and suitable as a starting point for a real restaurant/asporto order management tool.
