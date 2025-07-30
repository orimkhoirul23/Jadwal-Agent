API Solver Penjadwalan Karyawan dengan OR-Tools
Repositori ini berisi backend API yang dirancang untuk menyelesaikan masalah penjadwalan shift karyawan yang kompleks. API ini dibangun dengan Python, Flask, dan menggunakan Google OR-Tools (CP-SAT Solver) untuk menemukan solusi jadwal yang optimal berdasarkan serangkaian aturan bisnis yang ketat dan berbagai preferensi.

Fitur Utama API ✨
Endpoint Tunggal: Menyediakan satu endpoint /generate-schedule yang menerima semua data mentah dan mengembalikan jadwal yang sudah jadi.

Optimisasi Berbasis Constraint: Menggunakan Constraint Programming untuk menangani puluhan aturan yang saling berhubungan secara efisien.

Kombinasi Hard & Soft Constraints: Mampu membedakan antara aturan yang wajib dipenuhi (hard) dan preferensi yang diusahakan (soft) untuk menghasilkan jadwal terbaik.

Pemrosesan Asinkron (Polling): Dirancang untuk menangani proses solving yang mungkin memakan waktu lama dengan mengembalikan URL status yang bisa diperiksa secara berkala.

Output Terstruktur: Menghasilkan jadwal lengkap dan ringkasan harian dalam format JSON yang bersih.

Arsitektur & Teknologi ⚙️
Framework: Flask sebagai web server untuk menerima request.

Mesin Solver: Google OR-Tools (CP-SAT) sebagai inti dari logika optimisasi.

Antrian Tugas (Task Queue): Celery untuk mengelola dan menjalankan tugas-tugas berat (seperti proses solving) secara terpisah di latar belakang (background worker).

Message Broker: Redis atau RabbitMQ (pilih salah satu) sebagai perantara yang menyimpan antrian tugas untuk Celery.

Dependensi: pandas dan openpyxl untuk pemrosesan data dan pembuatan file Excel.

Endpoint API 🚀
POST /generate-schedule


Body Request (JSON)
```json
{
  "year": 2025,
  "month": 8,
  "requests": [
  {
      "nip": "400192",
      "jenis": "Libur",
      "tanggal": "2025-08-18"
    }
  ],
  "public_holidays": [
    "2025-08-17"
  ]
}
```
```json
Respon Sukses 
{
  "message": "Proses pembuatan jadwal dimulai.",
  "status_check_url": "/status/some-unique-task-id"
}
```
2. GET /status/<task_id>
Frontend menggunakan status_check_url yang diterima untuk menanyakan status tugas secara berkala (misalnya, setiap 5 detik).

Respons Saat Proses Berjalan (PENDING)

```json
{
  "state": "PENDING",
  "status": "Tugas sedang menunggu untuk dijalankan atau sedang dalam proses."
}
```
Response Succes 
```json
{
  "state": "SUCCESS",
  "status": "Tugas berhasil diselesaikan.",
  "result": {
    "schedule": {
      "NIP1": ["ROLE1", "ROLE2", "Libur", "..."],
      "NIP2": ["ROLE3", "Libur", ROLE3", "..."]
    },
    "summary": {
      "1": { "ROLE1": 2, "ROLE2": 1, ... },
      "2": { "ROLE2": 1, "Libur": 2, ... }
    }
  }
}
```

