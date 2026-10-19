// SPDX-License-Identifier: GPL-3.0-or-later
package org.auggmented.scoreboard.viewer;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import android.view.inputmethod.InputMethodManager;

import java.net.HttpURLConnection;
import java.net.URL;
import java.io.IOException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;

/** A small server-connected viewer. The scoreboard and all sports requests remain on the server. */
public final class MainActivity extends Activity {
    public static final String PREFERENCES = "scoreboard-viewer";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService probeExecutor = Executors.newSingleThreadExecutor();
    private final Runnable retry = this::probeServer;
    private final Runnable loadTimeout = () -> failInitialLoad("The scoreboard server took too long to respond.");
    private final Runnable rendererRetry = this::restartAfterRendererFailure;
    private SharedPreferences preferences;
    private FrameLayout root;
    private WebView webView;
    private TextView status;
    private ScrollView setup;
    private String serverUrl = "";
    private String activeNavigationUrl = "";
    private volatile HttpURLConnection activeConnection;
    private boolean visible;
    private boolean destroyed;
    private boolean pageReady;
    private boolean mainLoadFailed;
    private boolean loading;
    private boolean probing;
    private boolean menuOpen;
    private boolean rendererFailed;
    private int failedAttempts;
    private int generation;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        preferences = getSharedPreferences(PREFERENCES, MODE_PRIVATE);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(7, 16, 24));
        setContentView(root);
        try {
            webView = new WebView(this);
        } catch (RuntimeException error) {
            TextView missing = text("Android System WebView is unavailable. Enable or update the device's WebView provider, then reopen this app.", 22);
            root.addView(missing);
            return;
        }
        webView.setBackgroundColor(Color.rgb(7, 16, 24));
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setSupportZoom(false);
        if (Build.VERSION.SDK_INT >= 26) settings.setSafeBrowsingEnabled(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false);
        WebView.setWebContentsDebuggingEnabled(false);
        webView.setWebViewClient(new Client());
        webView.setOnLongClickListener(view -> { showMenu(); return true; });
        root.addView(webView, new FrameLayout.LayoutParams(-1, -1));
        status = text("Connecting to scoreboard…", 20);
        status.setGravity(Gravity.CENTER);
        status.setPadding(dp(30), dp(30), dp(30), dp(30));
        FrameLayout.LayoutParams statusLayout = new FrameLayout.LayoutParams(-1, -1);
        root.addView(status, statusLayout);
        Button menu = new Button(this);
        menu.setText("⋮");
        menu.setTextSize(22);
        menu.setContentDescription("Viewer menu");
        menu.setAlpha(0.65f);
        menu.setOnClickListener(view -> showMenu());
        FrameLayout.LayoutParams menuLayout = new FrameLayout.LayoutParams(dp(48), dp(48), Gravity.TOP | Gravity.END);
        root.addView(menu, menuLayout);
        serverUrl = preferences.getString("server_url", "");
        if (serverUrl.isEmpty()) showSetup();
        else {
            try {
                serverUrl = ViewerPolicy.normalizeUrl(serverUrl);
            } catch (IllegalArgumentException error) {
                serverUrl = "";
                showSetup();
            }
        }
        fullscreen();
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private TextView text(String value, int size) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(Color.WHITE);
        return view;
    }

    private void showSetup() {
        cancelPending();
        if (webView != null) webView.stopLoading();
        generation++;
        loading = false;
        probing = false;
        if (setup != null) root.removeView(setup);
        setup = new ScrollView(this);
        setup.setFillViewport(true);
        setup.setBackgroundColor(Color.rgb(7, 16, 24));
        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(28), dp(36), dp(28), dp(28));
        form.addView(text("Auggmented Scoreboard", 27));
        TextView description = text("Connect to your existing scoreboard server on the same network. This app does not collect scores or replace the server.", 17);
        description.setPadding(0, dp(14), 0, dp(16));
        form.addView(description);
        EditText address = new EditText(this);
        address.setTextColor(Color.WHITE);
        address.setHintTextColor(Color.LTGRAY);
        address.setSingleLine(true);
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        address.setHint("http://192.168.1.50:5000/");
        address.setText(serverUrl);
        address.setContentDescription("Scoreboard server URL");
        form.addView(address, new LinearLayout.LayoutParams(-1, dp(60)));
        CheckBox bootNotice = new CheckBox(this);
        bootNotice.setText("Offer a launch notification after reboot (where supported)");
        bootNotice.setTextColor(Color.WHITE);
        bootNotice.setChecked(preferences.getBoolean("notify_after_boot", false));
        form.addView(bootNotice);
        form.addView(text("Automatic app launch after reboot depends on your device's kiosk/launcher configuration. Back or the ⋮ button opens the maintenance menu.", 15));
        Button open = new Button(this);
        open.setText("Save and open scoreboard");
        open.setOnClickListener(view -> {
            String normalized;
            try {
                normalized = ViewerPolicy.normalizeUrl(address.getText().toString());
            } catch (IllegalArgumentException error) {
                address.setError(error.getMessage());
                address.requestFocus();
                return;
            }
            if (!preferences.edit().putString("server_url", normalized)
                    .putBoolean("notify_after_boot", bootNotice.isChecked()).commit()) {
                Toast.makeText(this, "Could not save settings. Free some device storage and try again.", Toast.LENGTH_LONG).show();
                return;
            }
            InputMethodManager keyboard = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
            if (keyboard != null) keyboard.hideSoftInputFromWindow(address.getWindowToken(), 0);
            if (bootNotice.isChecked() && Build.VERSION.SDK_INT >= 33) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
            }
            serverUrl = normalized;
            root.removeView(setup);
            setup = null;
            pageReady = false;
            failedAttempts = 0;
            loadPage();
        });
        form.addView(open);
        setup.addView(form, new ScrollView.LayoutParams(-1, -2));
        root.addView(setup, new FrameLayout.LayoutParams(-1, -1));
        open.requestFocus();
    }

    private void showMenu() {
        if (menuOpen || destroyed || isFinishing()) return;
        menuOpen = true;
        new AlertDialog.Builder(this).setTitle("Scoreboard viewer")
                .setItems(new String[]{"Return to scoreboard", "Change server address", "Reconnect now", "Open server settings in browser", "Exit viewer", "About / source license"},
                        (dialog, selected) -> {
                            if (selected == 0 && setup != null && !serverUrl.isEmpty()) {
                                root.removeView(setup);
                                setup = null;
                                if (pageReady && webView != null) status.setVisibility(View.GONE);
                                else loadPage();
                            } else if (selected == 1) showSetup();
                            else if (selected == 2 && !serverUrl.isEmpty()) {
                                if (setup != null) { root.removeView(setup); setup = null; }
                                pageReady = false;
                                failedAttempts = 0;
                                loadPage();
                            } else if (selected == 3 && !serverUrl.isEmpty()) {
                                Uri uri = Uri.parse(serverUrl);
                                Uri settingsUrl = uri.buildUpon().path("/settings").clearQuery().fragment(null).build();
                                try { startActivity(new Intent(Intent.ACTION_VIEW, settingsUrl)); }
                                catch (RuntimeException error) {
                                    Toast.makeText(this, "Open " + settingsUrl + " on your phone to manage settings.", Toast.LENGTH_LONG).show();
                                }
                            } else if (selected == 4) finish();
                            else if (selected == 5) new AlertDialog.Builder(this)
                                    .setTitle("Auggmented Scoreboard viewer 0.1.0")
                                    .setMessage("Server-connected viewer; a running scoreboard server is required.\n\nGPLv3 or later. License included in the APK's assets/LICENSE.\n\nCorresponding source and build instructions:\nhttps://github.com/BtCodex/Auggment-Scoreboard-Fork\nSee docs/ANDROID_VIEWER.md in the development branch.")
                                    .setPositiveButton("Close", null).show();
                        })
                .setOnDismissListener(dialog -> { menuOpen = false; fullscreen(); }).show();
    }

    private void fullscreen() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                | View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
    }

    private void loadPage() {
        if (!visible || destroyed || setup != null || serverUrl.isEmpty()) return;
        if (webView == null) { recreate(); return; }
        cancelPending();
        generation++;
        mainLoadFailed = false;
        loading = true;
        activeNavigationUrl = serverUrl;
        status.setText("Connecting to scoreboard…\n" + serverUrl + "\nBack opens the viewer menu.");
        status.setVisibility(View.VISIBLE);
        webView.loadUrl(serverUrl);
        handler.postDelayed(loadTimeout, 20_000L);
    }

    private void failInitialLoad(String reason) {
        if (destroyed || webView == null || setup != null || pageReady || mainLoadFailed) return;
        mainLoadFailed = true;
        loading = false;
        webView.stopLoading();
        handler.removeCallbacks(loadTimeout);
        scheduleRetry(reason);
    }

    private void scheduleRetry(String reason) {
        if (!visible || destroyed || setup != null) return;
        handler.removeCallbacks(retry);
        long delay = ViewerPolicy.retryDelayMillis(failedAttempts++);
        status.setText(reason + "\nRetrying in " + (delay / 1000) + " seconds.\n" + serverUrl + "\nBack opens the viewer menu.");
        status.setVisibility(View.VISIBLE);
        handler.postDelayed(retry, delay);
    }

    private void probeServer() {
        if (!visible || destroyed || probing || loading || pageReady || setup != null) return;
        probing = true;
        final int expectedGeneration = generation;
        final String expectedUrl = serverUrl;
        try {
            probeExecutor.execute(() -> {
                boolean ready = false;
                HttpURLConnection connection = null;
                try {
                    connection = openProbe(expectedUrl, "HEAD");
                    activeConnection = connection;
                    int code = connection.getResponseCode();
                    if (code == 405 || code == 501) {
                        // Some reverse proxies disable HEAD even though the display GET works.
                        connection.disconnect();
                        connection = openProbe(expectedUrl, "GET");
                        activeConnection = connection;
                        code = connection.getResponseCode();
                    }
                    ready = code >= 200 && code < 400;
                } catch (Exception ignored) {
                    // Report a retry status rather than replace the page with a system error screen.
                } finally {
                    if (connection != null) connection.disconnect();
                    activeConnection = null;
                }
                final boolean successful = ready;
                handler.post(() -> {
                    if (destroyed || expectedGeneration != generation) return;
                    probing = false;
                    if (!visible || setup != null) return;
                    if (successful) loadPage();
                    else scheduleRetry("The scoreboard server is unavailable. Check its address and Wi-Fi.");
                });
            });
        } catch (RejectedExecutionException ignored) { probing = false; }
    }

    private HttpURLConnection openProbe(String url, String method) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) new URL(url).openConnection();
        connection.setConnectTimeout(5000);
        connection.setReadTimeout(5000);
        connection.setRequestMethod(method);
        connection.setInstanceFollowRedirects(false);
        connection.setUseCaches(false);
        return connection;
    }

    private void pageLoaded() {
        handler.removeCallbacks(loadTimeout);
        loading = false;
        if (mainLoadFailed || setup != null) return;
        pageReady = true;
        failedAttempts = 0;
        status.setVisibility(View.GONE);
        fullscreen();
    }

    private void cancelPending() {
        handler.removeCallbacks(retry);
        handler.removeCallbacks(loadTimeout);
        handler.removeCallbacks(rendererRetry);
    }

    private void restartAfterRendererFailure() {
        if (visible && !destroyed) recreate();
    }

    private boolean currentNavigation(WebView view, String url) {
        return !destroyed && view == webView && setup == null && url != null
                && ViewerPolicy.sameOrigin(serverUrl, url) && url.equals(activeNavigationUrl);
    }

    private boolean currentPage(WebView view, String url) {
        return currentNavigation(view, url) && url.equals(view.getUrl());
    }

    private final class Client extends WebViewClient {
        @Override public void onPageStarted(WebView view, String url, Bitmap favicon) {
            // getUrl() can still name the previous page at this point in WebView's lifecycle.
            if (destroyed || view != webView || setup != null || !ViewerPolicy.sameOrigin(serverUrl, url)) return;
            activeNavigationUrl = url;
            generation++;
            pageReady = false;
            mainLoadFailed = false;
            loading = true;
            handler.removeCallbacks(loadTimeout);
            handler.postDelayed(loadTimeout, 20_000L);
        }
        @Override public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return !ViewerPolicy.sameOrigin(serverUrl, url);
        }
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            return request.isForMainFrame() && !ViewerPolicy.sameOrigin(serverUrl, request.getUrl().toString());
        }
        @Override public void onPageFinished(WebView view, String url) {
            if (mainLoadFailed || !currentPage(view, url)) return;
            final int expectedGeneration = generation;
            // Older Fire OS builds can contain a WebView too old for the scoreboard's JavaScript.
            view.evaluateJavascript("typeof updateData==='function' && typeof ScoreboardClock!=='undefined'", result -> {
                if (mainLoadFailed || generation != expectedGeneration || !currentPage(view, url)) return;
                if ("true".equals(result)) pageLoaded();
                else failInitialLoad("The server responded, but the scoreboard did not initialize. Update Android System WebView/Fire OS and verify the server address.");
            });
        }
        @Override public void onReceivedError(WebView view, int code, String description, String url) {
            if (Build.VERSION.SDK_INT < 23 && currentNavigation(view, url)) failInitialLoad("Unable to connect to the scoreboard server.");
        }
        @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame() && currentNavigation(view, request.getUrl().toString())) failInitialLoad("Unable to connect to the scoreboard server.");
        }
        @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
            if (request.isForMainFrame() && currentNavigation(view, request.getUrl().toString())) failInitialLoad("The server returned HTTP " + response.getStatusCode() + ".");
        }
        @Override public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            if (view != webView || destroyed) return true;
            cancelPending();
            generation++;
            pageReady = false;
            mainLoadFailed = true;
            activeNavigationUrl = "";
            loading = false;
            probing = false;
            rendererFailed = true;
            root.removeView(view);
            view.destroy();
            webView = null;
            status.setText("Android WebView stopped. Reopening in 30 seconds.\nBack opens the viewer menu.");
            status.setVisibility(View.VISIBLE);
            if (visible) handler.postDelayed(rendererRetry, 30_000L);
            return true;
        }
    }

    @Override public void onResume() {
        super.onResume();
        visible = true;
        if (webView == null) {
            if (rendererFailed && setup == null) handler.postDelayed(rendererRetry, 30_000L);
            return;
        }
        webView.onResume();
        fullscreen();
        if (setup == null && !serverUrl.isEmpty()) {
            if (pageReady) {
                // Existing JS retains cached scores through data-request failures; do not reload it.
                webView.evaluateJavascript("if(typeof updateData==='function'){updateData();}", null);
            } else if (!loading && !probing) loadPage();
            else if (loading) handler.postDelayed(loadTimeout, 20_000L);
        }
    }

    @Override public void onPause() {
        visible = false;
        cancelPending();
        if (webView != null) webView.onPause();
        super.onPause();
    }

    @Override public void onDestroy() {
        destroyed = true;
        cancelPending();
        if (activeConnection != null) activeConnection.disconnect();
        probeExecutor.shutdownNow();
        if (webView != null) {
            webView.stopLoading();
            root.removeView(webView);
            webView.destroy();
        }
        super.onDestroy();
    }

    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (focused) fullscreen();
    }

    @Override public void onBackPressed() { showMenu(); }

    @Override public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_MENU) { showMenu(); return true; }
        return super.onKeyUp(keyCode, event);
    }
}
