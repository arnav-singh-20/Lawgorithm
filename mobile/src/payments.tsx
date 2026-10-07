// Razorpay Standard Checkout inside the app. The server creates the order
// and later verifies the payment (backend/payments/razorpay.py) -- the app
// only shows Razorpay's own checkout page and passes the result back.
import React from "react";
import { Linking, Modal, Platform, Pressable, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { WebView } from "react-native-webview";

import { createOrder, Payment } from "./api";
import { API_BASE } from "./config";
import { useI18n } from "./i18n";
import { fonts, useTheme } from "./theme";

export type Order = { order_id: string; amount: number; currency: string; key_id: string };

export async function prepareOrder(purpose: "analysis" | "expert"): Promise<Order> {
  return createOrder(purpose) as Promise<Order>;
}

function checkoutHtml(order: Order, name: string, description: string) {
  const options = JSON.stringify({ key: order.key_id, order_id: order.order_id, amount: order.amount, currency: order.currency,
    name, description: description.slice(0, 60), theme: { color: "#E8962E" } });
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#F7F4EE"><script src="https://checkout.razorpay.com/v1/checkout.js"></script><script>
  var send = function (m) { window.ReactNativeWebView.postMessage(JSON.stringify(m)); };
  var o = ${options};
  o.handler = function (r) { send({ ok: true, payment: r }); };
  o.modal = { ondismiss: function () { send({ ok: false }); } };
  var rzp = new Razorpay(o);
  rzp.on("payment.failed", function () { send({ failed: true }); });
  rzp.open();
</script></body></html>`;
}

/** Full-screen Razorpay checkout. onDone(payment) when paid, onDone(null) when closed. */
export function PaySheet({ order, description, onDone }: { order: Order | null; description: string; onDone: (p: Payment | null) => void }) {
  const t = useTheme();
  const { t: tr } = useI18n();
  if (!order) return null;

  if (Platform.OS === "web") {
    // Browser preview: use Razorpay's script directly.
    const w = window as any;
    const open = () => {
      const rzp = new w.Razorpay({ key: order.key_id, order_id: order.order_id, amount: order.amount, currency: order.currency, name: "Lawgorithm",
        description, theme: { color: "#E8962E" }, handler: (r: Payment) => onDone(r), modal: { ondismiss: () => onDone(null) } });
      rzp.open();
    };
    if (w.Razorpay) open();
    else {
      const s = document.createElement("script");
      s.src = "https://checkout.razorpay.com/v1/checkout.js";
      s.onload = open;
      s.onerror = () => onDone(null);
      document.head.append(s);
    }
    return null;
  }

  return (
    <Modal visible animationType="slide" onRequestClose={() => onDone(null)}>
      <SafeAreaView style={{ flex: 1, backgroundColor: "#F7F4EE" }}>
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 14 }}>
          <Text style={{ fontFamily: fonts.bold, fontSize: 16, color: "#0b0b0c" }}>🔒 {tr("app.payTitle")}</Text>
          <Pressable onPress={() => onDone(null)} hitSlop={10} accessibilityRole="button">
            <Text style={{ fontFamily: fonts.medium, fontSize: 15, color: t.soft }}>{tr("app.close")}</Text>
          </Pressable>
        </View>
        <WebView
          originWhitelist={["*"]}
          source={{ html: checkoutHtml(order, "Lawgorithm", description), baseUrl: API_BASE }}
          onMessage={e => {
            try {
              const m = JSON.parse(e.nativeEvent.data);
              if (m.ok) onDone(m.payment as Payment);
              else if (!m.failed) onDone(null);      // failed: they can retry inside the checkout
            } catch { onDone(null); }
          }}
          // UPI apps (GPay, PhonePe, Paytm...) open outside the web view
          onShouldStartLoadWithRequest={req => {
            if (/^(upi|intent|tez|phonepe|paytmmp|gpay):/i.test(req.url)) {
              Linking.openURL(req.url).catch(() => {});
              return false;
            }
            return true;
          }}
          setSupportMultipleWindows={false}
        />
      </SafeAreaView>
    </Modal>
  );
}
