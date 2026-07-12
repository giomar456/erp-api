package com.ggerp.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.AssetFileDescriptor;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.media.ToneGenerator;
import android.net.Uri;
import android.os.Build;
import android.os.IBinder;
import android.util.Base64;

import androidx.core.app.NotificationCompat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.HashSet;
import java.util.LinkedList;
import java.util.Locale;
import java.util.Queue;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class DocumentMonitorService extends Service {
    private static final String CHANNEL_ID = "erp_caja_monitor";
    private static final String ALERT_CHANNEL_ID = "erp_caja_alertas_v2";
    private static final String RADIO_CHANNEL_ID = "erp_boquitoqui_audio_v2";
    private static final String BASE_URL = "http://64.181.176.160:8000/documentos/ultimo?sucursal=computer_army&empresa=computer_army";
    private static final String RADIO_URL = "http://64.181.176.160:8000/boquitoqui/live?sucursal=computer_army&empresa=computer_army";
    private static final String PREFS = "gg_erp_radio";
    private ScheduledExecutorService executor;
    private String lastKey = "";
    private long lastRadioId = 0;
    private boolean radioInitialized = true;
    private boolean radioPlaying = false;
    private final Queue<JSONObject> radioPlaybackQueue = new LinkedList<>();
    private final Set<Long> playedRadioIds = new HashSet<>();
    private boolean initialized = false;
    private int documentTick = 0;

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
        startForeground(2401, buildNotification("Radio y caja activos"));
        executor = Executors.newSingleThreadScheduledExecutor();
        executor.scheduleWithFixedDelay(() -> {
            documentTick++;
            if (documentTick >= 30) {
                documentTick = 0;
                checkDocuments();
            }
            checkRadioMessages();
        }, 1, 500, TimeUnit.MILLISECONDS);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (executor != null) {
            executor.shutdownNow();
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    "ERP Caja",
                    NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Monitorea boletas y facturas nuevas para sonar en caja.");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
                NotificationChannel alertChannel = new NotificationChannel(
                        ALERT_CHANNEL_ID,
                        "ERP Caja alertas",
                        NotificationManager.IMPORTANCE_HIGH
                );
                alertChannel.setDescription("Avise cuando se emite una boleta, factura o nota de venta.");
                Uri soundUri = Uri.parse("android.resource://" + getPackageName() + "/" + R.raw.cash_register);
                AudioAttributes audioAttributes = new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build();
                alertChannel.setSound(soundUri, audioAttributes);
                manager.createNotificationChannel(alertChannel);
                NotificationChannel radioChannel = new NotificationChannel(
                        RADIO_CHANNEL_ID,
                        "ERP Boquitoqui",
                        NotificationManager.IMPORTANCE_LOW
                );
                radioChannel.setDescription("Muestra mensajes de boquitoqui sin sonido de alerta; el audio se reproduce automaticamente.");
                radioChannel.setSound(null, null);
                manager.createNotificationChannel(radioChannel);
            }
        }
    }

    private Notification buildNotification(String text) {
        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(getApplicationInfo().icon)
                .setContentTitle("G&G ERP Caja")
                .setContentText(text)
                .setOngoing(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .build();
    }

    private Notification buildAlertNotification(JSONObject doc) {
        String type = doc.optString("tipo", "DOCUMENTO");
        String number = doc.optString("numero", "");
        String total = doc.optString("total", "");
        Intent intent = new Intent(this, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        intent.putExtra("open_view", "caja");
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent pendingIntent = PendingIntent.getActivity(this, 2501, intent, flags);
        return new NotificationCompat.Builder(this, ALERT_CHANNEL_ID)
                .setSmallIcon(getApplicationInfo().icon)
                .setContentTitle("Documento emitido")
                .setContentText(type + " " + number + " / S/ " + total)
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)
                .setSound(Uri.parse("android.resource://" + getPackageName() + "/" + R.raw.cash_register))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .build();
    }

    private Notification buildRadioNotification(JSONObject msg) {
        String user = msg.optString("usuario_emisor", "Usuario");
        Intent intent = new Intent(this, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        intent.putExtra("open_view", "radio");
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent pendingIntent = PendingIntent.getActivity(this, 2601, intent, flags);
        return new NotificationCompat.Builder(this, RADIO_CHANNEL_ID)
                .setSmallIcon(getApplicationInfo().icon)
                .setContentTitle("Boquitoqui G&G ERP")
                .setContentText("Mensaje de voz de " + user)
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .build();
    }

    private void checkDocuments() {
        try {
            HttpURLConnection connection = (HttpURLConnection) new URL(BASE_URL).openConnection();
            connection.setConnectTimeout(10000);
            connection.setReadTimeout(10000);
            connection.setRequestMethod("GET");
            int status = connection.getResponseCode();
            if (status < 200 || status >= 300) return;

            BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream()));
            StringBuilder builder = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line);
            }
            reader.close();

            JSONObject newest = parseNewestDocument(builder.toString());
            if (newest == null) return;

            String key = newest.optString("key");
            if (key == null || key.length() == 0) {
                key = newest.optString("id") + "-"
                        + newest.optString("numero") + "-"
                        + newest.optString("total");
            }

            if (!initialized) {
                initialized = true;
                lastKey = key;
                return;
            }
            if (!key.equals(lastKey)) {
                lastKey = key;
                playCashSound();
                showDocumentAlert(newest);
            }
        } catch (Exception ignored) {
            // The next scheduled check retries without interrupting the app.
        }
    }

    private JSONArray parseDocuments(String raw) throws Exception {
        String text = raw == null ? "" : raw.trim();
        if (text.startsWith("[")) return new JSONArray(text);
        JSONObject obj = new JSONObject(text);
        if (obj.has("data") && obj.get("data") instanceof JSONArray) return obj.getJSONArray("data");
        if (obj.has("documentos") && obj.get("documentos") instanceof JSONArray) return obj.getJSONArray("documentos");
        if (obj.has("items") && obj.get("items") instanceof JSONArray) return obj.getJSONArray("items");
        return new JSONArray();
    }

    private JSONObject parseNewestDocument(String raw) throws Exception {
        String text = raw == null ? "" : raw.trim();
        if (text.startsWith("{")) {
            JSONObject obj = new JSONObject(text);
            if (obj.has("data") && !obj.isNull("data")) {
                return obj.getJSONObject("data");
            }
            if (obj.has("id")) {
                return obj;
            }
        }
        JSONArray docs = parseDocuments(text);
        return newestCashDocument(docs);
    }

    private JSONObject newestCashDocument(JSONArray docs) {
        JSONObject newest = null;
        long newestId = Long.MIN_VALUE;
        for (int i = 0; i < docs.length(); i++) {
            JSONObject doc = docs.optJSONObject(i);
            if (doc == null) continue;
            String type = doc.optString("tipo", "").toUpperCase(Locale.ROOT);
            if (!type.equals("BOLETA") && !type.equals("FACTURA") && !type.equals("NOTA DE VENTA")) continue;
            long id = doc.optLong("id", i);
            if (newest == null || id > newestId) {
                newest = doc;
                newestId = id;
            }
        }
        return newest;
    }

    private void checkRadioMessages() {
        try {
            SharedPreferences prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE);
            boolean enabled = prefs.getBoolean("enabled", true);
            String user = prefs.getString("user", "");
            if (!enabled || user == null || user.trim().length() == 0) return;

            String endpoint = RADIO_URL
                    + "&usuario=" + java.net.URLEncoder.encode(user, "UTF-8")
                    + "&since_id=" + lastRadioId
                    + "&limit=8";
            HttpURLConnection connection = (HttpURLConnection) new URL(endpoint).openConnection();
            connection.setConnectTimeout(10000);
            connection.setReadTimeout(10000);
            connection.setRequestMethod("GET");
            int status = connection.getResponseCode();
            if (status < 200 || status >= 300) return;

            BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream()));
            StringBuilder builder = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line);
            }
            reader.close();

            JSONArray messages = parseRadioMessages(builder.toString());
            if (messages.length() == 0) return;
            long newestId = lastRadioId;
            for (int i = 0; i < messages.length(); i++) {
                JSONObject msg = messages.optJSONObject(i);
                if (msg == null) continue;
                long id = msg.optLong("id", 0);
                if (id <= 0) continue;
                if (id > newestId) newestId = id;
                String sender = msg.optString("usuario_emisor", "");
                if (!radioInitialized) continue;
                if (!sender.equalsIgnoreCase(user)) {
                    enqueueRadioVoice(msg);
                    if (i == messages.length() - 1) showRadioAlert(msg);
                }
            }
            if (!radioInitialized) radioInitialized = true;
            lastRadioId = newestId;
        } catch (Exception ignored) {
            // The next scheduled check retries without interrupting the app.
        }
    }

    private JSONArray parseRadioMessages(String raw) throws Exception {
        String text = raw == null ? "" : raw.trim();
        if (text.startsWith("[")) return new JSONArray(text);
        JSONObject obj = new JSONObject(text);
        if (obj.has("data") && obj.get("data") instanceof JSONArray) return obj.getJSONArray("data");
        if (obj.has("items") && obj.get("items") instanceof JSONArray) return obj.getJSONArray("items");
        if (obj.has("mensajes") && obj.get("mensajes") instanceof JSONArray) return obj.getJSONArray("mensajes");
        JSONArray one = new JSONArray();
        if (obj.has("data") && obj.get("data") instanceof JSONObject) one.put(obj.getJSONObject("data"));
        return one;
    }

    private void showRadioAlert(JSONObject msg) {
        try {
            NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (manager != null) {
                manager.notify(2601, buildRadioNotification(msg));
            }
        } catch (Exception ignored) {
            // Sound remains the primary alert.
        }
    }

    private void enqueueRadioVoice(JSONObject msg) {
        synchronized (radioPlaybackQueue) {
            long id = msg.optLong("id", 0);
            if (id > 0 && playedRadioIds.contains(id)) return;
            if (id > 0) playedRadioIds.add(id);
            if (playedRadioIds.size() > 200) playedRadioIds.clear();
            radioPlaybackQueue.add(msg);
            if (radioPlaying) return;
            radioPlaying = true;
        }
        new Thread(() -> {
            while (true) {
                JSONObject next;
                synchronized (radioPlaybackQueue) {
                    next = radioPlaybackQueue.poll();
                    if (next == null) {
                        radioPlaying = false;
                        return;
                    }
                }
                playRadioVoiceSync(next);
            }
        }).start();
    }

    private void playRadioVoiceSync(JSONObject msg) {
            MediaPlayer player = null;
            File temp = null;
            try {
                String base64 = msg.optString("audio_base64", "");
                if (base64 == null || base64.length() == 0) return;
                byte[] audioBytes = Base64.decode(base64, Base64.DEFAULT);
                String mime = msg.optString("audio_mime", "audio/wav").toLowerCase(Locale.ROOT);
                String ext = mime.contains("wav") ? ".wav" : ".webm";
                temp = File.createTempFile("gg_radio_", ext, getCacheDir());
                FileOutputStream out = new FileOutputStream(temp);
                try {
                    out.write(audioBytes);
                } finally {
                    out.close();
                }
                player = new MediaPlayer();
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                    player.setAudioAttributes(new AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_MEDIA)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                            .build());
                } else {
                    player.setAudioStreamType(AudioManager.STREAM_MUSIC);
                }
                player.setDataSource(temp.getAbsolutePath());
                player.prepare();
                player.setVolume(1.0f, 1.0f);
                player.start();
                while (player.isPlaying()) {
                    Thread.sleep(120);
                }
            } catch (Exception ignored) {
                // If the device cannot decode the audio in background, keep the radio silent instead of playing an alert tone.
            } finally {
                if (player != null) {
                    try {
                        player.release();
                    } catch (Exception ignored) {
                        // No-op.
                    }
                }
                if (temp != null) {
                    try {
                        temp.delete();
                    } catch (Exception ignored) {
                        // No-op.
                    }
                }
            }
    }

    private void playCashSound() {
        new Thread(() -> {
            MediaPlayer player = null;
            ToneGenerator tone = null;
            try {
                AssetFileDescriptor afd = getResources().openRawResourceFd(R.raw.cash_register);
                if (afd != null) {
                    player = new MediaPlayer();
                    try {
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                            player.setAudioAttributes(new AudioAttributes.Builder()
                                    .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                                    .build());
                        } else {
                            player.setAudioStreamType(AudioManager.STREAM_NOTIFICATION);
                        }
                        player.setDataSource(afd.getFileDescriptor(), afd.getStartOffset(), afd.getLength());
                        player.prepare();
                    } finally {
                        afd.close();
                    }
                    player.setVolume(1.0f, 1.0f);
                    player.start();
                    Thread.sleep(900);
                    return;
                }
                tone = new ToneGenerator(AudioManager.STREAM_NOTIFICATION, 90);
                tone.startTone(ToneGenerator.TONE_PROP_BEEP, 90);
                Thread.sleep(120);
                tone.startTone(ToneGenerator.TONE_PROP_ACK, 110);
                Thread.sleep(150);
                tone.startTone(ToneGenerator.TONE_PROP_BEEP2, 170);
            } catch (Exception ignored) {
                // Sound is best-effort if Android audio focus blocks notification tones.
            } finally {
                if (player != null) {
                    player.release();
                }
                if (tone != null) {
                    try {
                        Thread.sleep(220);
                    } catch (Exception ignored) {
                        // No-op.
                    }
                    tone.release();
                }
            }
        }).start();
    }

    private void showDocumentAlert(JSONObject doc) {
        try {
            NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (manager != null) {
                manager.notify(2501, buildAlertNotification(doc));
            }
        } catch (Exception ignored) {
            // Notification is secondary; the cash sound is the important signal.
        }
    }
}
