<?php
session_start();
include_once "ui/connectdb.php"; // Ensure this file sets up your PDO connection in $pdo

if (isset($_POST['btn_login'])) {
    // Sanitize and get inputs
    $email = filter_input(INPUT_POST, 'txt_email', FILTER_SANITIZE_EMAIL);
    $password = $_POST['txt_password'];

    try {
        // Prepare statement to fetch employee details
        $stmt = $pdo->prepare("
            SELECT employee_id, first_name, last_name, email, password_hash, role 
            FROM employees 
            WHERE email = :email
        ");
        $stmt->bindParam(':email', $email);
        $stmt->execute();
        $employee = $stmt->fetch(PDO::FETCH_ASSOC);

        // Check if employee exists and password is correct
        if ($employee && password_verify($password, $employee['password_hash'])) {
            // Set session variables
            $_SESSION['employee_id'] = $employee['employee_id'];
            $_SESSION['first_name'] = $employee['first_name'];
            $_SESSION['last_name'] = $employee['last_name'];
            $_SESSION['email'] = $employee['email'];
            $_SESSION['role'] = $employee['role'];

            // Insert a new record into the user_logins table
            $stmtLog = $pdo->prepare("
                INSERT INTO user_logins (employee_id, login_time, ip_address) 
                VALUES (:employee_id, NOW(), :ip)
            ");
            $stmtLog->execute([
                ':employee_id' => $employee['employee_id'],
                ':ip' => $_SERVER['REMOTE_ADDR']
            ]);
            // Save the inserted log_id in the session to update it later on logout
            $_SESSION['login_log_id'] = $pdo->lastInsertId();

            // Role-based redirection
            switch($employee['role']) {    
                case 'Owner':
                case 'Admin': 
                    $_SESSION['status'] = "Login successful as " . $employee['role'];
                    $_SESSION['status_code'] = "success";
                    header('Location: ui/tablereport.php');
                    exit;
                case 'Cashier':
                    $_SESSION['status'] = "Login successful as " . $employee['role'];
                    $_SESSION['status_code'] = "success";
                    header('Location: ui/pos.php');
                    exit;
                default:
                    header('Location: index.php');
                    exit;
            }
        } else {
            // Login failed: set error message and redirect back to login page
            $_SESSION['status'] = "Invalid email or password";
            $_SESSION['status_code'] = "error";
            header('Location: index.php');
            exit;
        }
    } catch (PDOException $e) {
        $_SESSION['status'] = "Database error: " . $e->getMessage();
        $_SESSION['status_code'] = "error";
        header('Location: index.php');
        exit;
    }
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>School Store POS | Login</title>
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="mobile-web-app-capable" content="yes">
    
    <!-- Stylesheets -->
    <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Source+Sans+Pro:300,400,400i,700&display=fallback">
    <link rel="stylesheet" href="plugins/fontawesome-free/css/all.min.css">
    <link rel="stylesheet" href="plugins/sweetalert2-theme-bootstrap-4/bootstrap-4.min.css">
    <link rel="stylesheet" href="dist/css/sccpos.css">
</head>

<body class="hold-transition login-page">
    <div class="login-box">
        <div class="login-header text-center">  
            <a href="index.php" class="login_title display-4" style="color: #004085;">
                <i class="fas fa-store"></i> School Store POS
            </a>
        </div>
        
        <div class="card card-outline card-primary">
            <div class="card-body">
                <p class="login-box-msg">Sign in to start your session</p>

                <form method="post">
                    <div class="input-group mb-3">
                        <input type="email" 
                               class="form-control" 
                               name="txt_email" 
                               placeholder="Email"
                               required
                               autocomplete="username">
                        <div class="input-group-append">
                            <div class="input-group-text">
                                <span class="fas fa-envelope"></span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="input-group mb-3">
                        <input type="password" 
                               class="form-control" 
                               name="txt_password" 
                               placeholder="Password"
                               required
                               autocomplete="current-password">
                        <div class="input-group-append">
                            <div class="input-group-text">
                                <span class="fas fa-lock"></span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="row justify-content-center">
                        <div class="col-6">
                            <button type="submit" 
                                    class="btn btn-primary btn-block" 
                                    name="btn_login"
                                    onclick="requestFullscreen()">
                                Sign In
                            </button>
                        </div>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Scripts -->
    <script src="plugins/jquery/jquery.min.js"></script>
    <script src="plugins/bootstrap/js/bootstrap.bundle.min.js"></script>
    <script src="plugins/sweetalert2/sweetalert2.min.js"></script>

    <!-- Fullscreen Script -->
    <script>
    function requestFullscreen() {
        try {
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen().then(() => {
                    sessionStorage.setItem('fullscreen', 'true');
                }).catch(err => {
                    console.log('Fullscreen error:', err);
                });
            }
        } catch (e) {
            console.log('Fullscreen exception:', e);
        }
    }

    // Initialize fullscreen if flag exists
    if (sessionStorage.getItem('fullscreen')) {
        requestFullscreen();
    }
    </script>

    <?php if (isset($_SESSION['status'])): ?>
    <script>
    $(function() {
        const Toast = Swal.mixin({
            toast: true,
            position: 'top-end',
            showConfirmButton: false,
            timer: 3000
        });

        Toast.fire({
            icon: '<?= $_SESSION['status_code'] ?>',
            title: '<?= $_SESSION['status'] ?>'
        });
    });
    </script>
    <?php 
        unset($_SESSION['status']);
        unset($_SESSION['status_code']);
    endif; ?>
</body>
</html>
