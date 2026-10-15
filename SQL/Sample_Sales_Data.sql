-- ============================================================================
-- Sample sales data: what a billing system might hold. Used by the demo jobs
-- that run SQL (DEV-BILLING-INVOICE_EXPORT), so they have something real-
-- looking to query. The people and companies are made up.
--
-- Portable SQL: runs on SQLite and on MariaDB. autoapp/create_dev_db.py loads
-- it into /tmp/autoapp_sample/sales.db; for MariaDB, create a database for it
-- (e.g. autoapp_sales) and run this file there.
-- ============================================================================

CREATE TABLE customers (
    customer_id   INTEGER      NOT NULL PRIMARY KEY,
    customer_code VARCHAR(20)  NOT NULL,
    customer_name VARCHAR(100) NOT NULL,
    city          VARCHAR(60),
    country       CHAR(2)
);

CREATE TABLE invoices (
    invoice_id    INTEGER       NOT NULL PRIMARY KEY,
    invoice_no    VARCHAR(20)   NOT NULL,
    customer_id   INTEGER       NOT NULL REFERENCES customers (customer_id),
    invoice_date  DATE          NOT NULL,
    due_date      DATE          NOT NULL,
    total_amount  DECIMAL(12,2) NOT NULL,
    status        VARCHAR(10)   NOT NULL      -- OPEN, PAID or OVERDUE
);

CREATE TABLE invoice_lines (
    line_id       INTEGER       NOT NULL PRIMARY KEY,
    invoice_id    INTEGER       NOT NULL REFERENCES invoices (invoice_id),
    line_no       INTEGER       NOT NULL,
    description   VARCHAR(100)  NOT NULL,
    quantity      DECIMAL(10,2) NOT NULL,
    unit          VARCHAR(10)   NOT NULL,
    unit_price    DECIMAL(12,2) NOT NULL,
    line_amount   DECIMAL(12,2) NOT NULL
);

CREATE TABLE payments (
    payment_id    INTEGER       NOT NULL PRIMARY KEY,
    invoice_id    INTEGER       NOT NULL REFERENCES invoices (invoice_id),
    payment_date  DATE          NOT NULL,
    amount        DECIMAL(12,2) NOT NULL,
    method        VARCHAR(10)   NOT NULL,     -- ACH, WIRE or CARD
    reference     VARCHAR(30)
);

INSERT INTO customers (customer_id, customer_code, customer_name, city, country) VALUES
(1, 'ACME', 'Acme Corporation', 'Chicago', 'US'),
(2, 'GLOBEX', 'Globex Ltd', 'London', 'GB'),
(3, 'INITECH', 'Initech Inc', 'Austin', 'US'),
(4, 'UMBRELLA', 'Umbrella Holdings', 'Toronto', 'CA'),
(5, 'STARK', 'Stark Industries', 'New York', 'US'),
(6, 'WAYNE', 'Wayne Enterprises', 'Gotham', 'US'),
(7, 'TYRELL', 'Tyrell Corporation', 'Los Angeles', 'US'),
(8, 'WONKA', 'Wonka Confections', 'Manchester', 'GB'),
(9, 'CYBERDYNE', 'Cyberdyne Systems', 'Sunnyvale', 'US'),
(10, 'SOYLENT', 'Soylent Foods', 'Rotterdam', 'NL');

INSERT INTO invoices (invoice_id, invoice_no, customer_id, invoice_date, due_date, total_amount, status) VALUES
(1, 'INV-2026-0001', 9, '2026-07-01', '2026-07-31', 2980.00, 'PAID'),
(2, 'INV-2026-0002', 6, '2026-07-06', '2026-08-05', 4410.00, 'PAID'),
(3, 'INV-2026-0003', 4, '2026-07-07', '2026-08-06', 2437.50, 'PAID'),
(4, 'INV-2026-0004', 7, '2026-07-12', '2026-08-11', 2070.00, 'PAID'),
(5, 'INV-2026-0005', 2, '2026-07-13', '2026-08-12', 300.00, 'PAID'),
(6, 'INV-2026-0006', 7, '2026-07-17', '2026-08-16', 620.00, 'PAID'),
(7, 'INV-2026-0007', 5, '2026-07-20', '2026-08-19', 450.00, 'PAID'),
(8, 'INV-2026-0008', 4, '2026-07-22', '2026-08-21', 3360.00, 'PAID'),
(9, 'INV-2026-0009', 8, '2026-07-27', '2026-08-26', 150.00, 'PAID'),
(10, 'INV-2026-0010', 2, '2026-07-30', '2026-08-29', 2762.50, 'PAID'),
(11, 'INV-2026-0011', 4, '2026-08-01', '2026-08-31', 1695.00, 'PAID'),
(12, 'INV-2026-0012', 4, '2026-08-03', '2026-09-02', 900.00, 'PAID'),
(13, 'INV-2026-0013', 4, '2026-08-06', '2026-09-05', 960.00, 'PAID'),
(14, 'INV-2026-0014', 9, '2026-08-10', '2026-09-09', 5985.00, 'PAID'),
(15, 'INV-2026-0015', 5, '2026-08-13', '2026-09-12', 870.00, 'PAID'),
(16, 'INV-2026-0016', 10, '2026-08-15', '2026-09-14', 2690.00, 'PAID'),
(17, 'INV-2026-0017', 5, '2026-08-19', '2026-09-18', 7340.00, 'PAID'),
(18, 'INV-2026-0018', 7, '2026-08-21', '2026-09-20', 600.00, 'PAID'),
(19, 'INV-2026-0019', 7, '2026-08-25', '2026-09-24', 450.00, 'OVERDUE'),
(20, 'INV-2026-0020', 2, '2026-08-28', '2026-09-27', 3000.00, 'OVERDUE'),
(21, 'INV-2026-0021', 3, '2026-08-30', '2026-09-29', 3237.50, 'OVERDUE'),
(22, 'INV-2026-0022', 2, '2026-09-03', '2026-10-03', 1095.00, 'OVERDUE'),
(23, 'INV-2026-0023', 10, '2026-09-07', '2026-10-07', 3000.00, 'OPEN'),
(24, 'INV-2026-0024', 10, '2026-09-08', '2026-10-08', 3210.00, 'OPEN'),
(25, 'INV-2026-0025', 2, '2026-09-13', '2026-10-13', 3360.00, 'OPEN'),
(26, 'INV-2026-0026', 7, '2026-09-14', '2026-10-14', 2050.00, 'OPEN'),
(27, 'INV-2026-0027', 2, '2026-09-18', '2026-10-18', 5700.00, 'OPEN'),
(28, 'INV-2026-0028', 7, '2026-09-20', '2026-10-20', 2250.00, 'OPEN'),
(29, 'INV-2026-0029', 9, '2026-09-24', '2026-10-24', 2465.00, 'OPEN'),
(30, 'INV-2026-0030', 9, '2026-09-28', '2026-10-28', 2975.00, 'OPEN');

INSERT INTO invoice_lines (line_id, invoice_id, line_no, description, quantity, unit, unit_price, line_amount) VALUES
(1, 1, 1, 'Document preparation', 6.0, 'HOUR', 180.00, 1080.00),
(2, 1, 2, 'Court appearance', 2, 'EACH', 950.00, 1900.00),
(3, 2, 1, 'Litigation support', 6.0, 'HOUR', 310.00, 1860.00),
(4, 2, 2, 'Document preparation', 12.5, 'HOUR', 180.00, 2250.00),
(5, 2, 3, 'Filing fee', 2, 'EACH', 150.00, 300.00),
(6, 3, 1, 'Research', 3.5, 'HOUR', 125.00, 437.50),
(7, 3, 2, 'Research', 6.0, 'HOUR', 125.00, 750.00),
(8, 3, 3, 'Research', 6.0, 'HOUR', 125.00, 750.00),
(9, 3, 4, 'Research', 4.0, 'HOUR', 125.00, 500.00),
(10, 4, 1, 'Contract review', 8.0, 'HOUR', 240.00, 1920.00),
(11, 4, 2, 'Filing fee', 1, 'EACH', 150.00, 150.00),
(12, 5, 1, 'Filing fee', 2, 'EACH', 150.00, 300.00),
(13, 6, 1, 'Litigation support', 2.0, 'HOUR', 310.00, 620.00),
(14, 7, 1, 'Filing fee', 3, 'EACH', 150.00, 450.00),
(15, 8, 1, 'Court appearance', 3, 'EACH', 950.00, 2850.00),
(16, 8, 2, 'Contract review', 1.5, 'HOUR', 240.00, 360.00),
(17, 8, 3, 'Filing fee', 1, 'EACH', 150.00, 150.00),
(18, 9, 1, 'Filing fee', 1, 'EACH', 150.00, 150.00),
(19, 10, 1, 'Research', 1.5, 'HOUR', 125.00, 187.50),
(20, 10, 2, 'Litigation support', 1.5, 'HOUR', 310.00, 465.00),
(21, 10, 3, 'Research', 2.0, 'HOUR', 125.00, 250.00),
(22, 10, 4, 'Litigation support', 6.0, 'HOUR', 310.00, 1860.00),
(23, 11, 1, 'Contract review', 2.0, 'HOUR', 240.00, 480.00),
(24, 11, 2, 'Litigation support', 1.5, 'HOUR', 310.00, 465.00),
(25, 11, 3, 'Research', 6.0, 'HOUR', 125.00, 750.00),
(26, 12, 1, 'Filing fee', 3, 'EACH', 150.00, 450.00),
(27, 12, 2, 'Filing fee', 3, 'EACH', 150.00, 450.00),
(28, 13, 1, 'Contract review', 4.0, 'HOUR', 240.00, 960.00),
(29, 14, 1, 'Court appearance', 2, 'EACH', 950.00, 1900.00),
(30, 14, 2, 'Research', 12.5, 'HOUR', 125.00, 1562.50),
(31, 14, 3, 'Research', 12.5, 'HOUR', 125.00, 1562.50),
(32, 14, 4, 'Contract review', 4.0, 'HOUR', 240.00, 960.00),
(33, 15, 1, 'Filing fee', 1, 'EACH', 150.00, 150.00),
(34, 15, 2, 'Document preparation', 4.0, 'HOUR', 180.00, 720.00),
(35, 16, 1, 'Document preparation', 4.0, 'HOUR', 180.00, 720.00),
(36, 16, 2, 'Filing fee', 2, 'EACH', 150.00, 300.00),
(37, 16, 3, 'Document preparation', 4.0, 'HOUR', 180.00, 720.00),
(38, 16, 4, 'Court appearance', 1, 'EACH', 950.00, 950.00),
(39, 17, 1, 'Contract review', 12.5, 'HOUR', 240.00, 3000.00),
(40, 17, 2, 'Litigation support', 4.0, 'HOUR', 310.00, 1240.00),
(41, 17, 3, 'Court appearance', 3, 'EACH', 950.00, 2850.00),
(42, 17, 4, 'Research', 2.0, 'HOUR', 125.00, 250.00),
(43, 18, 1, 'Filing fee', 2, 'EACH', 150.00, 300.00),
(44, 18, 2, 'Filing fee', 2, 'EACH', 150.00, 300.00),
(45, 19, 1, 'Filing fee', 3, 'EACH', 150.00, 450.00),
(46, 20, 1, 'Contract review', 12.5, 'HOUR', 240.00, 3000.00),
(47, 21, 1, 'Filing fee', 2, 'EACH', 150.00, 300.00),
(48, 21, 2, 'Research', 2.0, 'HOUR', 125.00, 250.00),
(49, 21, 3, 'Research', 3.5, 'HOUR', 125.00, 437.50),
(50, 21, 4, 'Document preparation', 12.5, 'HOUR', 180.00, 2250.00),
(51, 22, 1, 'Document preparation', 3.5, 'HOUR', 180.00, 630.00),
(52, 22, 2, 'Litigation support', 1.5, 'HOUR', 310.00, 465.00),
(53, 23, 1, 'Filing fee', 1, 'EACH', 150.00, 150.00),
(54, 23, 2, 'Court appearance', 3, 'EACH', 950.00, 2850.00),
(55, 24, 1, 'Document preparation', 2.0, 'HOUR', 180.00, 360.00),
(56, 24, 2, 'Court appearance', 3, 'EACH', 950.00, 2850.00),
(57, 25, 1, 'Court appearance', 3, 'EACH', 950.00, 2850.00),
(58, 25, 2, 'Document preparation', 2.0, 'HOUR', 180.00, 360.00),
(59, 25, 3, 'Filing fee', 1, 'EACH', 150.00, 150.00),
(60, 26, 1, 'Contract review', 1.5, 'HOUR', 240.00, 360.00),
(61, 26, 2, 'Litigation support', 4.0, 'HOUR', 310.00, 1240.00),
(62, 26, 3, 'Filing fee', 3, 'EACH', 150.00, 450.00),
(63, 27, 1, 'Contract review', 8.0, 'HOUR', 240.00, 1920.00),
(64, 27, 2, 'Contract review', 8.0, 'HOUR', 240.00, 1920.00),
(65, 27, 3, 'Litigation support', 6.0, 'HOUR', 310.00, 1860.00),
(66, 28, 1, 'Document preparation', 12.5, 'HOUR', 180.00, 2250.00),
(67, 29, 1, 'Research', 8.0, 'HOUR', 125.00, 1000.00),
(68, 29, 2, 'Litigation support', 1.5, 'HOUR', 310.00, 465.00),
(69, 29, 3, 'Research', 8.0, 'HOUR', 125.00, 1000.00),
(70, 30, 1, 'Contract review', 6.0, 'HOUR', 240.00, 1440.00),
(71, 30, 2, 'Filing fee', 2, 'EACH', 150.00, 300.00),
(72, 30, 3, 'Litigation support', 3.5, 'HOUR', 310.00, 1085.00),
(73, 30, 4, 'Filing fee', 1, 'EACH', 150.00, 150.00);

INSERT INTO payments (payment_id, invoice_id, payment_date, amount, method, reference) VALUES
(1, 1, '2026-07-31', 2980.00, 'WIRE', 'WIRE-20260037'),
(2, 2, '2026-07-29', 4410.00, 'WIRE', 'WIRE-20260074'),
(3, 3, '2026-07-27', 2437.50, 'WIRE', 'WIRE-20260111'),
(4, 4, '2026-07-25', 2070.00, 'WIRE', 'WIRE-20260148'),
(5, 5, '2026-08-04', 300.00, 'ACH', 'ACH-20260185'),
(6, 6, '2026-08-21', 620.00, 'CARD', 'CARD-20260222'),
(7, 7, '2026-08-03', 450.00, 'ACH', 'ACH-20260259'),
(8, 8, '2026-08-12', 3360.00, 'CARD', 'CARD-20260296'),
(9, 9, '2026-08-14', 150.00, 'ACH', 'ACH-20260333'),
(10, 10, '2026-08-19', 2762.50, 'CARD', 'CARD-20260370'),
(11, 11, '2026-08-29', 1695.00, 'ACH', 'ACH-20260407'),
(12, 12, '2026-08-17', 900.00, 'CARD', 'CARD-20260444'),
(13, 13, '2026-09-10', 960.00, 'CARD', 'CARD-20260481'),
(14, 14, '2026-09-12', 5985.00, 'WIRE', 'WIRE-20260518'),
(15, 15, '2026-09-03', 870.00, 'WIRE', 'WIRE-20260555'),
(16, 16, '2026-09-06', 2690.00, 'WIRE', 'WIRE-20260592'),
(17, 17, '2026-09-22', 7340.00, 'ACH', 'ACH-20260629'),
(18, 18, '2026-09-07', 600.00, 'CARD', 'CARD-20260666'),
(19, 19, '2026-09-14', 225.00, 'ACH', 'ACH-20260703'),
(20, 21, '2026-09-19', 1618.75, 'ACH', 'ACH-20260740');
