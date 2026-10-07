// Yes/no question that works on phones (Alert) and in the web preview (confirm).
import { Alert, Platform } from "react-native";

export function confirmAsync(message: string, yes = "OK", no = "Cancel"): Promise<boolean> {
  if (Platform.OS === "web") return Promise.resolve(window.confirm(message));
  return new Promise(resolve => Alert.alert("", message, [
    { text: no, style: "cancel", onPress: () => resolve(false) },
    { text: yes, style: "destructive", onPress: () => resolve(true) },
  ], { cancelable: true, onDismiss: () => resolve(false) }));
}
