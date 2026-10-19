// SPDX-License-Identifier: GPL-3.0-or-later
package org.auggmented.scoreboard.viewer;

public final class ViewerPolicyTest {
    private static int passed;

    private static void check(boolean condition, String name) {
        if (!condition) throw new AssertionError(name);
        passed++;
    }

    private static void rejects(String value) {
        boolean rejected = false;
        try { ViewerPolicy.normalizeUrl(value); }
        catch (IllegalArgumentException expected) { rejected = true; }
        check(rejected, "reject invalid URL: " + value);
    }

    public static void main(String[] args) {
        check("http://192.168.1.50:5000/".equals(ViewerPolicy.normalizeUrl(" 192.168.1.50:5000 ")), "LAN URL normalization");
        check("https://scoreboard.example/".equals(ViewerPolicy.normalizeUrl("HTTPS://Scoreboard.Example")), "HTTPS and case normalization");
        check("http://raspberrypi.local:5000/".equals(ViewerPolicy.normalizeUrl("raspberrypi.local:5000")), "mDNS hostname");
        check("http://[fd00::2]:5000/".equals(ViewerPolicy.normalizeUrl("http://[fd00::2]:5000")), "IPv6 address");
        check("https://example.test/a%2Fb?q=a%26b".equals(ViewerPolicy.normalizeUrl("https://example.test/a%2Fb?q=a%26b")), "escaped URL separators preserved");
        rejects(null);
        rejects("");
        rejects("file:///etc/passwd");
        rejects("content://settings");
        rejects("javascript:alert(1)");
        rejects("http://user:password@example.test");
        rejects("http://example.test/#fragment");
        rejects("http://example.test:70000/");
        rejects("http://example.test:0/");
        rejects("http://not a host/");
        check(ViewerPolicy.sameOrigin("http://192.168.1.50:5000/", "http://192.168.1.50:5000/settings"), "same-origin settings navigation");
        check(ViewerPolicy.sameOrigin("https://example.test/", "https://EXAMPLE.test:443/path"), "default HTTPS port");
        check(!ViewerPolicy.sameOrigin("http://example.test/", "https://example.test/"), "scheme change blocked");
        check(!ViewerPolicy.sameOrigin("http://example.test/", "http://other.test/"), "external navigation blocked");
        check(!ViewerPolicy.sameOrigin("http://example.test:5000/", "http://example.test:5001/"), "port change blocked");
        check(!ViewerPolicy.sameOrigin("http://example.test/", "javascript:alert(1)"), "script navigation blocked");
        check(!ViewerPolicy.sameOrigin("http://example.test/", "http://user@example.test/"), "credential navigation blocked");
        check(ViewerPolicy.retryDelayMillis(0) == 2000, "initial retry is two seconds");
        check(ViewerPolicy.retryDelayMillis(1) == 4000, "retry backoff doubles");
        check(ViewerPolicy.retryDelayMillis(4) == 32000, "retry backs off after repeated failure");
        check(ViewerPolicy.retryDelayMillis(5) == 60000, "retry is capped at one minute");
        check(ViewerPolicy.retryDelayMillis(Integer.MAX_VALUE) == 60000, "long outages cannot overflow");
        check(ViewerPolicy.retryDelayMillis(-1) == 2000, "negative retry counter is safe");
        System.out.println(passed + " Android URL/reconnect policy tests passed.");
    }
}
