# Migracion G&G ERP a Vercel + Neon

Usar esta opcion si Koyeb pide tarjeta o plan Pro.

## 1. Neon PostgreSQL

1. Entra a https://neon.com
2. Sign up con GitHub o Google.
3. Crea un proyecto llamado `gg-erp`.
4. Copia el `DATABASE_URL`.

Neon Free indica que no requiere tarjeta.

## 2. Subir archivos a GitHub

Sube estos archivos al repo `giomar456/erp-api`:

- `api.py`
- `api/index.py`
- `vercel.json`
- `requirements-api.txt`
- `VERCEL_NEON_MIGRACION.md`

Puedes usar `ABRIR_PUBLICAR_VERCEL_GITHUB.bat`.

## 3. Vercel

1. Entra a https://vercel.com
2. Import Project.
3. Selecciona GitHub repo `giomar456/erp-api`.
4. Framework: Other.
5. Root Directory: deja raiz del repo.
6. Variables de entorno:

```text
DATABASE_URL=postgresql://...
APP_VERSION=1.0.19
APP_DOWNLOAD_URL=https://github.com/giomar456/erp-api/releases/download/v1.0.19/erp_sql_pro_v20_v1.0.19.exe
APP_EXE_NAME=erp_sql_pro_v20_v1.0.19.exe
APP_UPDATE_NOTES=Actualizacion G&G ERP v1.0.19: proformas/PDF con descripciones largas en varias lineas sin cortar ni invadir columnas.
ANDROID_APP_VERSION=1.15
ANDROID_APP_DOWNLOAD_URL=https://github.com/giomar456/erp-api/releases/download/v1.0.19/GG_ERP_TELEFONO_v1.15_PROFORMA_PREVIEW.apk
ANDROID_APP_APK_NAME=GG_ERP_TELEFONO_v1.15_PROFORMA_PREVIEW.apk
ANDROID_APP_UPDATE_NOTES=Actualizacion Android G&G ERP v1.15: Ventas procesa PROFORMA sin descontar stock/caja y agrega vista previa para compartir o descargar con formato de impresion.
```

7. Deploy.

## 4. Inicializar tablas

Cuando Vercel termine, abre:

```text
https://TU-PROYECTO.vercel.app/init
```

Luego prueba:

```text
https://TU-PROYECTO.vercel.app/app/version
```

## 5. Actualizar apps

Con el dominio nuevo, reemplazar:

```text
https://erp-api-7x3d.onrender.com
```

en:

- `api_client.py`
- `my-react-app/src/App.jsx`

Luego generar instalador PC y APK Android nuevos.
