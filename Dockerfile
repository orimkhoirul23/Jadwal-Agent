# 1. Gunakan base image Python resmi yang ringan
FROM python:3.11-slim

# 2. Set direktori kerja di dalam container
WORKDIR /app

# 3. Salin file requirements terlebih dahulu untuk caching yang lebih baik
COPY requirements.txt .

# 4. Install semua library yang dibutuhkan
RUN pip install --no-cache-dir -r requirements.txt

# 5. Salin sisa kode proyek Anda ke dalam container
COPY . .

# 6. (Opsional) Memberitahu Docker bahwa container akan listen di port 5000
EXPOSE 5001

# Perintah default ini bisa di-override oleh docker-compose,
# tapi baik untuk dokumentasi.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "api_server:app"]
