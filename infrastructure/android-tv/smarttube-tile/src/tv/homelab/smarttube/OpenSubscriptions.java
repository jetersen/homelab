package tv.homelab.smarttube;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Toast;

public final class OpenSubscriptions extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            Intent intent = new Intent(Intent.ACTION_MAIN).setComponent(new ComponentName(
                    "app.smarttube.fdroid",
                    "com.liskovsoft.smartyoutubetv2.tv.launchers.SubscriptionsLauncherActivity"));
            startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                    | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED));
        } catch (ActivityNotFoundException | SecurityException error) {
            Toast.makeText(this, "Could not open SmartTube", Toast.LENGTH_SHORT).show();
        } finally {
            finish();
        }
    }
}
