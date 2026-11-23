-- SMMS relational schema (generated from Phase 4 data design; portable SQL, runs on SQLite and PostgreSQL)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS account (
  account_id INTEGER PRIMARY KEY AUTOINCREMENT,
  email VARCHAR(255) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(12) NOT NULL CHECK (role IN ('Visitor', 'Staff', 'Manager', 'ITAdmin')),
  is_active BOOLEAN NOT NULL DEFAULT true,
  email_verified BOOLEAN NOT NULL DEFAULT false,
  mfa_enabled BOOLEAN NOT NULL DEFAULT false,
  mfa_secret VARCHAR(64),
  failed_login_count INT NOT NULL DEFAULT 0,
  lock_until TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visitor (
  visitor_id INT PRIMARY KEY REFERENCES account,
  display_name VARCHAR(100) NOT NULL,
  mobile_number VARCHAR(20),
  preferred_language CHAR(2) NOT NULL CHECK (preferred_language IN ('EN', 'AR')),
  text_size VARCHAR(10) NOT NULL DEFAULT 'normal',
  high_contrast BOOLEAN NOT NULL DEFAULT false,
  consent_personalisation BOOLEAN NOT NULL DEFAULT false,
  consent_withdrawn_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS staff (
  staff_id INT PRIMARY KEY REFERENCES account,
  full_name VARCHAR(100) NOT NULL,
  department VARCHAR(60)
);

CREATE TABLE IF NOT EXISTS manager (
  manager_id INT PRIMARY KEY REFERENCES account,
  full_name VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS it_admin (
  admin_id INT PRIMARY KEY REFERENCES account
);

CREATE TABLE IF NOT EXISTS verification_token (
  token_hash CHAR(64) PRIMARY KEY,
  account_id INT NOT NULL REFERENCES account,
  purpose VARCHAR(16) NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
  expires_at TIMESTAMP NOT NULL,
  used_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS category (
  category_id INTEGER PRIMARY KEY AUTOINCREMENT,
  name VARCHAR(60) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS interest_profile (
  profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
  visitor_id INT NOT NULL UNIQUE REFERENCES visitor,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_category (
  profile_id INT,
  category_id INT,
  PRIMARY KEY (profile_id, category_id),
  FOREIGN KEY (profile_id) REFERENCES interest_profile,
  FOREIGN KEY (category_id) REFERENCES category
);

CREATE TABLE IF NOT EXISTS artifact (
  artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
  title VARCHAR(200) NOT NULL,
  category_id INT NOT NULL REFERENCES category,
  description TEXT,
  period VARCHAR(80),
  origin VARCHAR(80),
  condition VARCHAR(10) NOT NULL CHECK (condition IN ('excellent', 'good', 'fair', 'poor')),
  location VARCHAR(100) NOT NULL,
  status VARCHAR(20) NOT NULL CHECK (status IN ('onDisplay', 'inStorage', 'onLoan', 'underRestoration')),
  dimensions VARCHAR(80),
  acquisition_details TEXT,
  image_url VARCHAR(255),
  inspection_date DATE,
  is_archived BOOLEAN NOT NULL DEFAULT false,
  archive_reason VARCHAR(255),
  qr_code_value VARCHAR(64) NOT NULL UNIQUE,
  rfid_tag_id VARCHAR(64) UNIQUE,
  created_by INT NOT NULL REFERENCES staff,
  updated_by INT REFERENCES staff,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS condition_report (
  report_id INTEGER PRIMARY KEY AUTOINCREMENT,
  artifact_id INT NOT NULL REFERENCES artifact,
  rating VARCHAR(10) NOT NULL CHECK (rating IN ('excellent', 'good', 'fair', 'poor')),
  notes TEXT,
  reported_by INT NOT NULL REFERENCES staff,
  reported_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS status_history (
  history_id INTEGER PRIMARY KEY AUTOINCREMENT,
  artifact_id INT NOT NULL REFERENCES artifact,
  field_name VARCHAR(40) NOT NULL,
  old_value VARCHAR(255),
  new_value VARCHAR(255),
  changed_by INT NOT NULL REFERENCES staff,
  changed_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS exhibition (
  exhibition_id INTEGER PRIMARY KEY AUTOINCREMENT,
  title VARCHAR(200) NOT NULL,
  gallery VARCHAR(80) NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL CHECK (end_date >= start_date),
  description TEXT
);

CREATE TABLE IF NOT EXISTS exhibition_item (
  exhibition_id INT,
  artifact_id INT,
  display_start_date DATE NOT NULL,
  display_end_date DATE NOT NULL,
  PRIMARY KEY (exhibition_id, artifact_id),
  FOREIGN KEY (exhibition_id) REFERENCES exhibition,
  FOREIGN KEY (artifact_id) REFERENCES artifact
);

CREATE TABLE IF NOT EXISTS time_slot (
  slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
  exhibition_id INT NOT NULL REFERENCES exhibition,
  slot_date DATE NOT NULL,
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  capacity INT NOT NULL CHECK (capacity > 0),
  confirmed_seats INT NOT NULL DEFAULT 0 CHECK (confirmed_seats >= 0 AND confirmed_seats <= capacity),
  UNIQUE (exhibition_id, slot_date, start_time)
);

CREATE TABLE IF NOT EXISTS ticket_type (
  ticket_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
  exhibition_id INT NOT NULL REFERENCES exhibition,
  name VARCHAR(50) NOT NULL,
  price NUMERIC(8,2) NOT NULL CHECK (price >= 0),
  per_booking_limit INT NOT NULL DEFAULT 10,
  UNIQUE (exhibition_id, name)
);

CREATE TABLE IF NOT EXISTS booking (
  booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_reference VARCHAR(16) NOT NULL UNIQUE,
  visitor_id INT NOT NULL REFERENCES visitor,
  slot_id INT NOT NULL REFERENCES time_slot,
  ticket_type_id INT NOT NULL REFERENCES ticket_type,
  quantity INT NOT NULL CHECK (quantity > 0),
  total_price NUMERIC(10,2) NOT NULL,
  status VARCHAR(10) NOT NULL CHECK (status IN ('pending', 'confirmed', 'cancelled', 'completed')),
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS seat_hold (
  hold_id INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_id INT NOT NULL UNIQUE REFERENCES booking,
  slot_id INT NOT NULL REFERENCES time_slot,
  quantity INT NOT NULL CHECK (quantity > 0),
  expires_at TIMESTAMP NOT NULL,
  status VARCHAR(10) NOT NULL CHECK (status IN ('active', 'converted', 'expired', 'released'))
);

CREATE TABLE IF NOT EXISTS payment_record (
  payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_id INT NOT NULL UNIQUE REFERENCES booking,
  gateway_status VARCHAR(20) NOT NULL,
  amount NUMERIC(10,2) NOT NULL,
  currency CHAR(3) NOT NULL,
  transaction_ref VARCHAR(64) NOT NULL UNIQUE,
  paid_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS digital_ticket (
  ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_id INT NOT NULL REFERENCES booking,
  token VARCHAR(128) NOT NULL UNIQUE,
  status VARCHAR(10) NOT NULL CHECK (status IN ('unused', 'used', 'cancelled', 'expired')),
  issued_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS entry_validation (
  validation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticket_id INT NOT NULL REFERENCES digital_ticket,
  staff_id INT NOT NULL REFERENCES staff,
  result VARCHAR(8) NOT NULL CHECK (result IN ('valid', 'rejected')),
  reason VARCHAR(40),
  validated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS live_visitor_counter (
  counter_date DATE PRIMARY KEY,
  visitors_in INT NOT NULL CHECK (visitors_in >= 0),
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendation (
  recommendation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  visitor_id INT NOT NULL REFERENCES visitor,
  artifact_id INT NOT NULL REFERENCES artifact,
  rank INT NOT NULL CHECK (rank >= 1),
  reason VARCHAR(255) NOT NULL,
  shown_at TIMESTAMP NOT NULL,
  clicked BOOLEAN NOT NULL DEFAULT false,
  dismissed BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS feedback (
  feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
  visitor_id INT NOT NULL REFERENCES visitor,
  artifact_id INT NOT NULL REFERENCES artifact,
  rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment TEXT,
  submitted_at TIMESTAMP NOT NULL,
  UNIQUE (visitor_id, artifact_id)
);

CREATE TABLE IF NOT EXISTS knowledge_entry (
  entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
  artifact_id INT REFERENCES artifact,
  question VARCHAR(300) NOT NULL,
  answer TEXT NOT NULL,
  language CHAR(2) NOT NULL CHECK (language IN ('EN', 'AR')),
  status VARCHAR(12) NOT NULL CHECK (status IN ('draft', 'published', 'unpublished')),
  source_page VARCHAR(200),
  updated_by INT REFERENCES staff,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_session (
  session_id INTEGER PRIMARY KEY AUTOINCREMENT,
  visitor_id INT NOT NULL REFERENCES visitor,
  language CHAR(2) NOT NULL,
  started_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_turn (
  turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INT NOT NULL REFERENCES chat_session,
  entry_id INT REFERENCES knowledge_entry,
  question TEXT NOT NULL,
  answer TEXT,
  was_fallback BOOLEAN NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS ar_content (
  content_id INTEGER PRIMARY KEY AUTOINCREMENT,
  artifact_id INT NOT NULL UNIQUE REFERENCES artifact,
  model_url VARCHAR(255) NOT NULL,
  file_size_mb NUMERIC(4,1) NOT NULL CHECK (file_size_mb <= 20),
  overlay_text TEXT,
  published BOOLEAN NOT NULL DEFAULT false,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS ar_session (
  ar_session_id INTEGER PRIMARY KEY AUTOINCREMENT,
  content_id INT NOT NULL REFERENCES ar_content,
  started_at TIMESTAMP NOT NULL,
  duration_seconds INT,
  device_type VARCHAR(30),
  used_fallback BOOLEAN NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS report_export (
  report_id INTEGER PRIMARY KEY AUTOINCREMENT,
  generated_by INT NOT NULL REFERENCES manager,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  filter_exhibition_id INT REFERENCES exhibition,
  filter_ticket_type_id INT REFERENCES ticket_type,
  format VARCHAR(3) NOT NULL CHECK (format IN ('PDF', 'CSV')),
  generated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  log_id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type VARCHAR(20) NOT NULL CHECK (event_type IN ('login', 'failedLogin', 'roleChange', 'artifactChange', 'ticketValidation', 'accessDenied')),
  user_id INT REFERENCES account,
  event_time TIMESTAMP NOT NULL,
  details TEXT
);

CREATE TABLE IF NOT EXISTS notification (
  notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INT NOT NULL REFERENCES account,
  booking_id INT REFERENCES booking,
  channel VARCHAR(6) NOT NULL CHECK (channel IN ('email', 'sms', 'inApp')),
  type VARCHAR(14) NOT NULL CHECK (type IN ('confirmation', 'cancellation', 'reminder', 'passwordReset')),
  status VARCHAR(8) NOT NULL CHECK (status IN ('sent', 'failed', 'retrying')),
  attempts INT NOT NULL DEFAULT 0,
  sent_at TIMESTAMP
);

-- extra indexes (Phase 4, Section 4.3)
CREATE UNIQUE INDEX IF NOT EXISTS ux_entry_valid_once ON entry_validation(ticket_id) WHERE result = 'valid';
CREATE INDEX IF NOT EXISTS ix_artifact_search ON artifact(category_id, status, location);
CREATE INDEX IF NOT EXISTS ix_artifact_title ON artifact(title);
CREATE INDEX IF NOT EXISTS ix_slot_exh_date ON time_slot(exhibition_id, slot_date);
CREATE INDEX IF NOT EXISTS ix_booking_visitor ON booking(visitor_id, created_at);
CREATE INDEX IF NOT EXISTS ix_ticket_token ON digital_ticket(token);
CREATE INDEX IF NOT EXISTS ix_reco_visitor ON recommendation(visitor_id, shown_at);
CREATE INDEX IF NOT EXISTS ix_kb_status ON knowledge_entry(status, language);
CREATE INDEX IF NOT EXISTS ix_audit_time ON audit_log(event_time, event_type);
CREATE INDEX IF NOT EXISTS ix_hold_slot ON seat_hold(slot_id, status);
