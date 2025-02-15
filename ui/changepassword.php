<!-- changepassword.php (POS component) -->
<?php
include_once 'connectdb.php';
session_start();

// Check if the user is logged in; if not, redirect to the login page.
if (!isset($_SESSION['email']) || $_SESSION['role'] === 'Cashier') { 
    echo "<script>
            alert('Sorry, you can\'t access this. Please contact the Admin.');
            window.location.href = '../index.php';
          </script>"; 
    exit;
}

// Include the appropriate header based on user role.
if ($_SESSION['role'] == "Admin") {
    include_once "header.php";
} else {
    include_once "headeruser.php";
}

// When the user clicks on the "Update Password" button, process the form.
if (isset($_POST['btnupdate'])) {

    // 1. Retrieve values from the form.
    $oldpassword_txt = $_POST['txt_oldpassword'];
    $newpassword_txt = $_POST['txt_newpassword'];
    $rnewpassword_txt = $_POST['txt_rnewpassword'];

    // 2. Retrieve the logged-in user's email from the session.
    $email = $_SESSION['email'];

    // 3. Use a SELECT query to retrieve the employee record based on the email.
    $select = $pdo->prepare("SELECT * FROM employees WHERE email = :email");
    $select->bindParam(':email', $email);
    $select->execute();
    $row = $select->fetch(PDO::FETCH_ASSOC);

    // Get the hashed password from the database.
    $password_db = $row['password_hash'];

    // 4. Compare the provided old password with the password in the database.
    if (password_verify($oldpassword_txt, $password_db)) {
        // Check if the new passwords match.
        if ($newpassword_txt == $rnewpassword_txt) {
            // Hash the new password.
            $newpassword_hashed = password_hash($newpassword_txt, PASSWORD_DEFAULT);

            // 5. If they match, update the password.
            $update = $pdo->prepare("UPDATE employees SET password_hash = :pass WHERE email = :email");
            $update->bindParam(':pass', $newpassword_hashed);
            $update->bindParam(':email', $email);

            if ($update->execute()) {
                $_SESSION['status'] = "Password updated successfully";
                $_SESSION['status_code'] = "success";
            } else {
                $_SESSION['status'] = "Password update failed";
                $_SESSION['status_code'] = "error";
            }
        } else {
            $_SESSION['status'] = "New password does not match";
            $_SESSION['status_code'] = "error";
        }
    } else {
        $_SESSION['status'] = "Old password does not match";
        $_SESSION['status_code'] = "error";
    }
}
?>

<!-- Content Wrapper. Contains page content -->
<div class="content-wrapper">
    <!-- Content Header (Page header) -->
    <div class="content-header">
        <div class="container-fluid">
            <div class="row mb-2">
                <div class="col-sm-6">
                    <h1 class="m-0">Change Password</h1>
                </div><!-- /.col -->
                <div class="col-sm-6">
                    <ol class="breadcrumb float-sm-right">
                        <!-- Breadcrumb (if needed) -->
                    </ol>
                </div><!-- /.col -->
            </div><!-- /.row -->
        </div><!-- /.container-fluid -->
    </div>
    <!-- /.content-header -->

    <!-- Main content -->
    <div class="content">
        <div class="container-fluid">
            <div class="row">
                <div class="col-lg-12">
                    <!-- Horizontal Form -->
                    <div class="card card-info">
                        <div class="card-header">
                            <h3 class="card-title">Change Password</h3>
                        </div>
                        <!-- Form start -->
                        <form class="form-horizontal" action="" method="post">
                            <div class="card-body">
                                <div class="form-group row">
                                    <label for="txt_oldpassword" class="col-sm-2 col-form-label">Old Password</label>
                                    <div class="col-sm-10">
                                        <input type="password" class="form-control" id="txt_oldpassword" placeholder="Old Password" name="txt_oldpassword" required>
                                    </div>
                                </div>
                                <div class="form-group row">
                                    <label for="txt_newpassword" class="col-sm-2 col-form-label">New Password</label>
                                    <div class="col-sm-10">
                                        <input type="password" class="form-control" id="txt_newpassword" placeholder="New Password" name="txt_newpassword" required>
                                    </div>
                                </div>
                                <div class="form-group row">
                                    <label for="txt_rnewpassword" class="col-sm-2 col-form-label">Repeat New Password</label>
                                    <div class="col-sm-10">
                                        <input type="password" class="form-control" id="txt_rnewpassword" placeholder="Repeat Password" name="txt_rnewpassword" required>
                                    </div>
                                </div>
                            </div>
                            <!-- /.card-body -->
                            <div class="card-footer">
                                <button type="submit" class="btn btn-info" name="btnupdate">Update Password</button>
                            </div>
                            <!-- /.card-footer -->
                        </form>
                    </div>
                    <!-- /.card -->
                </div>
                <!-- /.col-lg-12 -->
            </div>
            <!-- /.row -->
        </div><!-- /.container-fluid -->
    </div>
    <!-- /.content -->
</div>
<!-- /.content-wrapper -->

<?php include_once "footer.php"; ?>

<?php
if (isset($_SESSION['status']) && $_SESSION['status'] != '') {
?>
    <script>
        Swal.fire({
            icon: '<?php echo $_SESSION['status_code']; ?>',
            title: '<?php echo $_SESSION['status']; ?>'
        });
    </script>
<?php
    unset($_SESSION['status']);
}
?>
