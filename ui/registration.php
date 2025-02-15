<!-- registration.php (POS component) -->
<?php
ob_start();
include_once 'connectdb.php';
session_start();

// Authorization check
if (!isset($_SESSION['email']) || $_SESSION['role'] === 'Cashier') { 
    echo "<script>
            alert('Sorry, you can\'t access this. Please contact the Admin.');
            window.location.href = '../index.php';
          </script>"; 
    exit;
}

// Include appropriate header
include_once ($_SESSION['role'] === 'Admin' || $_SESSION['role'] === 'Owner') ? "header.php" : "headeruser.php";

// Delete employee
if ($_SERVER['REQUEST_METHOD'] === 'GET' && isset($_GET['id'])) {
    $employee_id = filter_input(INPUT_GET, 'id', FILTER_VALIDATE_INT);
    
    if ($employee_id) {
        try {
            $delete = $pdo->prepare("DELETE FROM employees WHERE employee_id = :id");
            $delete->bindParam(':id', $employee_id, PDO::PARAM_INT);
            
            if ($delete->execute()) {
                $_SESSION['status'] = "Employee deleted successfully";
                $_SESSION['status_code'] = "success";
            } else {
                $_SESSION['status'] = "Error deleting employee";
                $_SESSION['status_code'] = "error";
            }
        } catch (PDOException $e) {
            $_SESSION['status'] = "Database error: " . $e->getMessage();
            $_SESSION['status_code'] = "error";
        }
    }
    header('Location: registration.php');
    exit;
}

// Add new employee
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['btnsave'])) {
    $first_name = trim($_POST['txtfirstname']);
    $last_name = trim($_POST['txtlastname']);
    $email = trim($_POST['txtemail']);
    $password = $_POST['txtpassword'];
    $role = $_POST['txtselect_option'];

    try {
        // Check if email exists
        $check = $pdo->prepare("SELECT email FROM employees WHERE email = :email");
        $check->bindParam(':email', $email);
        $check->execute();

        if ($check->rowCount() > 0) {
            $_SESSION['status'] = "Email already exists";
            $_SESSION['status_code'] = "warning";
        } else {
            // Hash password
            $password_hash = password_hash($password, PASSWORD_DEFAULT);

            $insert = $pdo->prepare("
                INSERT INTO employees 
                (first_name, last_name, email, password_hash, role)
                VALUES (:first_name, :last_name, :email, :password_hash, :role)
            ");

            $insert->bindParam(':first_name', $first_name);
            $insert->bindParam(':last_name', $last_name);
            $insert->bindParam(':email', $email);
            $insert->bindParam(':password_hash', $password_hash);
            $insert->bindParam(':role', $role);

            if ($insert->execute()) {
                $_SESSION['status'] = "Employee registered successfully";
                $_SESSION['status_code'] = "success";
            } else {
                $_SESSION['status'] = "Error registering employee";
                $_SESSION['status_code'] = "error";
            }
        }
    } catch (PDOException $e) {
        $_SESSION['status'] = "Database error: " . $e->getMessage();
        $_SESSION['status_code'] = "error";
    }
    header('Location: registration.php');
    exit;
}
?>

<!-- Content Wrapper. Contains page content -->
<div class="content-wrapper">
    <!-- Content Header (Page header) -->
    <div class="content-header">
        <div class="container-fluid">
            <div class="row mb-2">
                <div class="col-sm-6">
                    <h1 class="m-0">Employee Management</h1>
                </div>
            </div>
        </div>
    </div>

    <!-- Main content -->
    <div class="content">
        <div class="container-fluid">
            <div class="card card-primary card-outline">
                <div class="card-header">
                    <h5 class="m-0">Employee Registration</h5>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-4">
                            <form method="post">
                                <div class="form-group">
                                    <label>First Name</label>
                                    <input type="text" class="form-control" name="txtfirstname" required 
                                           pattern="[A-Za-z ]+" title="Letters only">
                                </div>
                                <div class="form-group">
                                    <label>Last Name</label>
                                    <input type="text" class="form-control" name="txtlastname" required 
                                           pattern="[A-Za-z ]+" title="Letters only">
                                </div>
                                <div class="form-group">
                                    <label>Email Address</label>
                                    <input type="email" class="form-control" name="txtemail" required>
                                </div>
                                <div class="form-group">
                                    <label>Password</label>
                                    <input type="password" class="form-control" name="txtpassword" 
                                           minlength="8" required>
                                </div>
                                <div class="form-group">
                                    <label>Role</label>
                                    <select class="form-control" name="txtselect_option" required>
                                        <option value="" disabled selected>Select Role</option>
                                        <option value="Admin">Admin</option>
                                        <option value="Cashier">Cashier</option>
                                        <?php if ($_SESSION['role'] === 'Owner'): ?>
                                            <option value="Owner">Owner</option>
                                        <?php endif; ?>
                                    </select>
                                </div>
                                <button type="submit" class="btn btn-primary" name="btnsave">Register</button>
                            </form>
                        </div>

                        <div class="col-md-8">
                            <table class="table table-striped table-hover">
                                <thead class="thead-dark">
                                    <tr>
                                        <th>ID</th>
                                        <th>Name</th>
                                        <th>Email</th>
                                        <th>Role</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <?php
                                    $select = $pdo->query("
                                        SELECT employee_id, first_name, last_name, email, role 
                                        FROM employees 
                                        ORDER BY employee_id ASC
                                    ");
                                    
                                    while ($row = $select->fetch(PDO::FETCH_OBJ)) {
                                        echo '
                                        <tr>
                                            <td>'.$row->employee_id.'</td>
                                            <td>'.htmlspecialchars($row->first_name.' '.$row->last_name).'</td>
                                            <td>'.htmlspecialchars($row->email).'</td>
                                            <td>'.$row->role.'</td>
                                            <td>
                                                <a href="registration.php?id='.$row->employee_id.'" 
                                                   class="btn btn-danger btn-sm" 
                                                   onclick="return confirm(\'Are you sure?\')">
                                                    <i class="fas fa-trash-alt"></i>
                                                </a>
                                            </td>
                                        </tr>';
                                    }
                                    ?>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<?php include_once "footer.php"; ?>

<?php if (isset($_SESSION['status'])): ?>
<script>
Swal.fire({
    icon: '<?= $_SESSION['status_code'] ?>',
    title: '<?= $_SESSION['status'] ?>'
});
</script>
<?php 
unset($_SESSION['status']);
unset($_SESSION['status_code']);
endif; ?>