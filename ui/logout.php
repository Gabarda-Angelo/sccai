<?php
session_start();
include_once "connectdb.php"; // Correct path if connectdb.php is in the same folder as logout.php

// Update the logout time if a login record exists
if (isset($_SESSION['login_log_id'])) {
    $stmtUpdate = $pdo->prepare("
        UPDATE user_logins 
        SET logout_time = NOW() 
        WHERE log_id = :log_id
    ");
    $stmtUpdate->execute([':log_id' => $_SESSION['login_log_id']]);
}

// Clear all session variables and destroy the session
session_unset();
session_destroy();

// Redirect to the login page
header('Location: ../index.php');
exit;
?>
