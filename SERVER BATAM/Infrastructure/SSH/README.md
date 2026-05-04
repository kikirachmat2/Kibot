# SSH Batam

Folder ini dipakai untuk menyimpan key aktif node Batam secara lokal.
File private/public key sengaja tidak ikut di-commit.

Target yang sudah terverifikasi:

- Host: `168.110.201.228`
- User: `ubuntu`
- Hostname: `antigravity-batam-1777042792`
- Fingerprint key aktif: `SHA256:RRebdJUP+5Ahw4MA+WNug7lQo27BvWsVRVx2Sp5RNGA`

Nama file lokal yang dipakai saat audit:

- `ssh-key-batam-active.pem`
- `ssh-key-batam-active.pub`

Contoh akses:

```bash
ssh -i SSH_BATAM/ssh-key-batam-active.pem ubuntu@168.110.201.228
```

Catatan:

- Instance Batam ini memakai pasangan key yang sebelumnya tertukar label sebagai `singapore.pem`.
- `batam.pem` lama bukan pasangan yang benar untuk instance ini.
