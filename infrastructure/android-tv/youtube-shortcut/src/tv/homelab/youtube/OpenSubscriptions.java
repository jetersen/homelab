package tv.homelab.youtube;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Toast;

/** A launcher entry point for the existing YouTube app, without account identifiers. */
public final class OpenSubscriptions extends Activity {
    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            startActivity(new Intent(Intent.ACTION_VIEW,
                    Uri.parse("https://www.youtube.com/feed/subscriptions"))
                    .setPackage("com.google.android.youtube.tv")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                            | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED));
        } catch (ActivityNotFoundException | SecurityException error) {
            Toast.makeText(this, "YouTube could not be opened", Toast.LENGTH_LONG).show();
        } finally {
            finish();
        }
    }
}
