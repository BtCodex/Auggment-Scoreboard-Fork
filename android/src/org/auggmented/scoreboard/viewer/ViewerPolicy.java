// SPDX-License-Identifier: GPL-3.0-or-later
package org.auggmented.scoreboard.viewer;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/** Dependency-free URL and reconnect rules, also tested on a desktop JDK. */
public final class ViewerPolicy {
    private ViewerPolicy() { }

    public static String normalizeUrl(String input) {
        if (input == null || input.trim().isEmpty()) {
            throw new IllegalArgumentException("Enter your scoreboard server address.");
        }
        String value = input.trim();
        if (value.length() > 2048) {
            throw new IllegalArgumentException("The server address is too long.");
        }
        if (!value.contains("://")) {
            value = "http://" + value;
        }
        try {
            URI uri = new URI(value);
            String scheme = uri.getScheme().toLowerCase(Locale.ROOT);
            if (!("http".equals(scheme) || "https".equals(scheme))
                    || uri.getHost() == null || uri.getHost().isEmpty()
                    || uri.getRawUserInfo() != null || uri.getRawFragment() != null
                    || uri.getPort() == 0 || uri.getPort() > 65535) {
                throw new IllegalArgumentException("Use an http:// or https:// server address without a password or # fragment.");
            }
            // Preserve escaped path/query separators instead of decoding %2F or %26.
            String path = uri.getRawPath().isEmpty() ? "/" : uri.getRawPath();
            String query = uri.getRawQuery() == null ? "" : "?" + uri.getRawQuery();
            return new URI(scheme + "://" + uri.getRawAuthority().toLowerCase(Locale.ROOT)
                    + path + query).toASCIIString();
        } catch (URISyntaxException error) {
            throw new IllegalArgumentException("Enter a valid server address, for example http://192.168.1.50:5000/.");
        }
    }

    public static boolean sameOrigin(String configuredUrl, String targetUrl) {
        try {
            URI server = new URI(normalizeUrl(configuredUrl));
            URI target = new URI(targetUrl);
            return target.getRawUserInfo() == null && target.getHost() != null
                    && server.getScheme().equalsIgnoreCase(target.getScheme())
                    && server.getHost().equalsIgnoreCase(target.getHost())
                    && effectivePort(server) == effectivePort(target);
        } catch (IllegalArgumentException | URISyntaxException error) {
            return false;
        }
    }

    private static int effectivePort(URI uri) {
        if (uri.getPort() >= 0) return uri.getPort();
        return "https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80;
    }

    public static long retryDelayMillis(int failedAttempts) {
        // Capped shift prevents overflow even after an extended outage.
        int exponent = Math.max(0, Math.min(failedAttempts, 5));
        return Math.min(60_000L, 2_000L << exponent);
    }
}
